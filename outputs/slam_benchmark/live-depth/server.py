"""Local, latest-frame stereo-depth experiment; never controls the cameras."""
import argparse
from collections import deque
from dataclasses import dataclass
from enum import Enum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import io
import json
from pathlib import Path
import signal
import threading
import time

import av
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent


class ErrorCode(str, Enum):
    CONNECT_OR_DECODE = 'connect_or_decode'
    GEOMETRY_MISMATCH = 'geometry_mismatch'
    PROCESSING = 'processing'
    STALE = 'stale'


@dataclass(frozen=True)
class DepthFrame:
    sequence: int
    received: float
    finished: float
    jpeg: bytes
    depth_npy: bytes
    mask_png: bytes
    valid_fraction: float
    processing_ms: float
    pts_seconds: float | None


class StereoDepth:
    """Private experimental processor; calibrated output reference is cam1/left."""
    def __init__(self, calibration):
        self.calibration_sha256 = hashlib.sha256(calibration.read_bytes()).hexdigest()
        with np.load(calibration, allow_pickle=False) as c:
            kl, dl, kr, dr = [c[k].copy() for k in ('K1', 'D1', 'K0', 'D0')]
            rotation = c['R_cam1_cam0'].T.copy()
            translation = -rotation @ c['T_cam1_cam0_m_assuming_20mm_squares'].reshape(3, 1)
        self.size = (544, 640)
        rl, rr, pl, pr, self.q = cv2.fisheye.stereoRectify(
            kl, dl, kr, dr, (1088, 1280), rotation, translation,
            flags=cv2.CALIB_ZERO_DISPARITY, newImageSize=self.size, balance=0.)
        if pr[0, 3] >= 0 or self.q[3, 2] <= 0:
            raise ValueError('Unexpected horizontal disparity sign')
        self.maps = [cv2.fisheye.initUndistortRectifyMap(k, d, r, p, self.size, cv2.CV_32FC1)
                     for k, d, r, p in ((kl, dl, rl, pl), (kr, dr, rr, pr))]
        self.supports = [cv2.erode(((mx >= 1) & (mx < 1086) & (my >= 1) & (my < 1278)).astype(np.uint8),
                                  np.ones((5, 5), np.uint8)).astype(bool) for mx, my in self.maps]
        settings = dict(numDisparities=128, blockSize=5, P1=200, P2=800,
                        disp12MaxDiff=1, preFilterCap=31, uniquenessRatio=10,
                        speckleWindowSize=100, speckleRange=2, mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY)
        self.match_left = cv2.StereoSGBM_create(minDisparity=0, **settings)
        self.match_right = cv2.StereoSGBM_create(minDisparity=-127, **settings)
        self.yy, self.xx = np.indices((640, 544))

    def compute(self, image, sequence, received, pts):
        start = time.monotonic()
        if image.shape != (1280, 2176):
            raise ValueError('Expected mirrored cam0/right + cam1/left at 2176x1280')
        inputs = (cv2.flip(image[:, 1088:], 1), cv2.flip(image[:, :1088], 1))
        left, right = [cv2.remap(im, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
                       for im, (mx, my) in zip(inputs, self.maps)]
        dl = self.match_left.compute(left, right).astype(np.float32)/16
        dr = self.match_right.compute(right, left).astype(np.float32)/16
        xr = self.xx-dl
        xi = np.clip(np.rint(xr).astype(np.int32), 0, 543)
        opposite = dr[self.yy, xi]
        valid = (self.supports[0] & (xr >= 0) & (xr <= 543) & self.supports[1][self.yy, xi]
                 & (dl > 0) & (dl < 127) & (opposite > -128) & (opposite < 0)
                 & (np.abs(dl+opposite) <= 1.))
        xyz = cv2.reprojectImageTo3D(dl, self.q)
        valid &= np.isfinite(xyz).all(axis=2) & (xyz[:, :, 2] > 0)
        depth = np.where(valid, xyz[:, :, 2], np.nan).astype(np.float32)
        color_index = np.rint((1-np.clip((np.nan_to_num(depth, nan=3.)-.2)/2.8, 0, 1))*255).astype(np.uint8)
        color = cv2.applyColorMap(color_index, cv2.COLORMAP_TURBO)
        color[~valid] = 0
        view = np.full((730, 1088, 3), 22, np.uint8)
        view[40:680, :544] = cv2.cvtColor(left, cv2.COLOR_GRAY2BGR)
        view[40:680, 544:] = color
        cv2.putText(view, 'RECTIFIED LEFT', (16, 27), 0, .6, (240, 240, 240), 1, cv2.LINE_AA)
        cv2.putText(view, f'DEPTH | valid {valid.mean()*100:.1f}%', (560, 27), 0, .6, (240, 240, 240), 1, cv2.LINE_AA)
        cv2.putText(view, '0.2m warm -> 3.0m cool | black=invalid | candidate calibration; accuracy unverified',
                    (16, 710), 0, .52, (230, 230, 230), 1, cv2.LINE_AA)
        ok, jpeg = cv2.imencode('.jpg', view, [cv2.IMWRITE_JPEG_QUALITY, 85])
        ok_mask, mask = cv2.imencode('.png', valid.astype(np.uint8)*255)
        if not ok or not ok_mask:
            raise RuntimeError('Image encoding failed')
        buffer = io.BytesIO()
        np.save(buffer, depth, allow_pickle=False)
        finished = time.monotonic()
        return DepthFrame(sequence, received, finished, jpeg.tobytes(), buffer.getvalue(), mask.tobytes(),
                          float(valid.mean()), (finished-start)*1000, pts)


class Pipeline:
    def __init__(self, processor, url):
        self.processor, self.url = processor, url
        self.stop = threading.Event()
        self.condition = threading.Condition()
        self.raw = self.output = None
        self.sequence = self.processed = self.skipped = self.reconnects = 0
        self.error = None
        self.completed = deque(maxlen=120)
        self.threads = []

    def set_error(self, code, detail):
        with self.condition:
            self.error = dict(code=code.value, detail=detail)
            self.raw = None
            self.output = None
            self.condition.notify_all()

    def capture(self):
        retry = 1
        while not self.stop.is_set():
            try:
                with av.open(self.url, options={'rtsp_transport': 'tcp', 'fflags': 'nobuffer', 'flags': 'low_delay'},
                             timeout=(5, 5)) as container:
                    stream = container.streams.video[0]
                    stream.thread_type = 'SLICE'
                    last_pts = None
                    for frame in container.decode(stream):
                        if self.stop.is_set():
                            return
                        received = time.monotonic()
                        if (frame.width, frame.height) != (2176, 1280):
                            self.set_error(ErrorCode.GEOMETRY_MISMATCH, f'{frame.width}x{frame.height}')
                            self.stop.wait(2)
                            break
                        pts = float(frame.pts*frame.time_base) if frame.pts is not None else None
                        if pts is not None and last_pts is not None and pts <= last_pts:
                            continue
                        last_pts = pts
                        gray = frame.to_ndarray(format='gray')
                        with self.condition:
                            self.sequence += 1
                            self.raw = (gray, self.sequence, received, pts)
                            self.error = None
                            self.condition.notify_all()
                        retry = 1
            except Exception as error:
                self.set_error(ErrorCode.CONNECT_OR_DECODE, str(error))
            if self.stop.wait(retry):
                return
            self.reconnects += 1
            retry = min(retry*2, 8)

    def process(self):
        previous = 0
        while not self.stop.is_set():
            with self.condition:
                self.condition.wait_for(lambda: self.stop.is_set() or (self.raw is not None and self.raw[1] != previous), .5)
                if self.stop.is_set():
                    return
                if self.raw is None or self.raw[1] == previous:
                    continue
                raw = self.raw
            try:
                output = self.processor.compute(*raw)
                with self.condition:
                    self.skipped += max(0, raw[1]-previous-1)
                    previous = raw[1]
                    # A capture failure during processing must invalidate this result.
                    if self.raw is not None and self.error is None:
                        self.output = output
                        self.processed += 1
                        self.completed.append(output.finished)
                        self.condition.notify_all()
            except Exception as error:
                previous = raw[1]
                self.set_error(ErrorCode.PROCESSING, str(error))

    def fresh(self):
        with self.condition:
            frame = self.output
            return frame if frame is not None and time.monotonic()-frame.received <= 2 else None

    def status(self):
        with self.condition:
            frame = self.output
            age = time.monotonic()-frame.received if frame else None
            fps = ((len(self.completed)-1)/(self.completed[-1]-self.completed[0])) if len(self.completed) > 1 else 0
            return dict(state='live' if age is not None and age <= 2 else 'unavailable',
                        decoded=self.sequence, processed=self.processed, skipped=self.skipped, reconnects=self.reconnects,
                        processing_fps=fps, frame_age_ms=age*1000 if age is not None else None,
                        processing_ms=frame.processing_ms if frame else None,
                        valid_fraction=frame.valid_fraction if frame else None, error=self.error,
                        source_pts_seconds=frame.pts_seconds if frame else None,
                        age_semantics='Since local decoder output; not sensor-to-display latency',
                        resolution=[544, 640], calibration_sha256=self.processor.calibration_sha256,
                        metric_accuracy_verified=False)

    def start(self):
        self.threads = [threading.Thread(target=fn, name=name) for fn, name in
                        ((self.capture, 'rtsp-reader'), (self.process, 'depth-worker'))]
        for thread in self.threads:
            thread.start()

    def close(self):
        self.stop.set()
        with self.condition:
            self.condition.notify_all()
        for thread in self.threads:
            thread.join(timeout=12)
        if any(thread.is_alive() for thread in self.threads):
            raise RuntimeError('Worker shutdown exceeded timeout')


def handler_for(pipeline):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, code, content_type, data):
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            try:
                if self.path == '/':
                    self.reply(200, 'text/html; charset=utf-8', (ROOT / 'index.html').read_bytes())
                elif self.path == '/status.json':
                    self.reply(200, 'application/json', json.dumps(pipeline.status()).encode())
                elif self.path in ('/snapshot.jpg', '/depth.npy', '/mask.png'):
                    frame = pipeline.fresh()
                    if frame is None:
                        self.reply(503, 'application/json', b'{"error":"stale_or_unavailable"}')
                    else:
                        data, kind = {'/snapshot.jpg': (frame.jpeg, 'image/jpeg'),
                                      '/depth.npy': (frame.depth_npy, 'application/octet-stream'),
                                      '/mask.png': (frame.mask_png, 'image/png')}[self.path]
                        self.reply(200, kind, data)
                elif self.path == '/stream.mjpg':
                    if pipeline.fresh() is None:
                        self.reply(503, 'application/json', b'{"error":"stale_or_unavailable"}')
                        return
                    self.connection.settimeout(3)
                    self.send_response(200)
                    self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
                    self.send_header('Cache-Control', 'no-store')
                    self.end_headers()
                    previous = -1
                    while not pipeline.stop.is_set():
                        with pipeline.condition:
                            pipeline.condition.wait_for(lambda: pipeline.stop.is_set() or
                                (pipeline.output is not None and pipeline.output.sequence != previous), .5)
                        frame = pipeline.fresh()
                        if frame is None:
                            return
                        if frame.sequence == previous:
                            continue
                        previous = frame.sequence
                        self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: '+
                                         str(len(frame.jpeg)).encode()+b'\r\n\r\n'+frame.jpeg+b'\r\n')
                        self.wfile.flush()
                else:
                    self.reply(404, 'text/plain', b'Not found')
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass
    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='rtsp://192.168.137.226:8554/stereo')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--seconds', type=float, default=0, help='0 runs until stop file or Ctrl+C')
    parser.add_argument('--stop-file', type=Path, default=ROOT / 'STOP')
    parser.add_argument('--report', type=Path, default=ROOT / 'last-run.json')
    args = parser.parse_args()
    cv2.setNumThreads(2)
    processor = StereoDepth(ROOT.parent / 'calibration-ready-20261014/geometry-analysis/stereo-candidate.npz')
    pipeline = Pipeline(processor, args.url)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_for(pipeline))
    server.timeout = .25
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: pipeline.stop.set())
    started = time.monotonic()
    pipeline.start()
    print(f'http://127.0.0.1:{args.port}/', flush=True)
    try:
        while not pipeline.stop.is_set() and not args.stop_file.exists():
            server.handle_request()
            if args.seconds > 0 and time.monotonic()-started >= args.seconds:
                break
    finally:
        pipeline.close()
        server.server_close()
        report = pipeline.status()
        report.update(wall_seconds=time.monotonic()-started, workers_joined=True)
        args.report.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
