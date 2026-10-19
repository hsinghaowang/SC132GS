"""Record a second RTSP client without pausing the server; preserve geometry provenance."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import queue
import shutil
import threading
import time

import av
from PIL import ImageOps

base = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--name', default='target-rtsp-redo-20261014')
parser.add_argument('--seconds', type=int, default=60)
parser.add_argument('--warmup', type=int, default=5)
args = parser.parse_args()
assert 2 <= args.seconds <= 90 and 0 <= args.warmup <= 10
assert args.name.replace('-', '').replace('_', '').isalnum()
session_name = args.name
session = base / 'live-calibration-20261013' / session_name
root = base / ('stereo-validation-' + session_name.removeprefix('target-'))
session.mkdir(exist_ok=False)
root.mkdir(exist_ok=False)
for eye in (0, 1):
    (session / f'cam{eye}').mkdir()
source = base / 'calibration-ready-20261014/geometry-analysis'
shutil.copyfile(source / 'stereo-candidate.npz', root / 'frozen-candidate.npz')
shutil.copyfile(source / 'report.json', root / 'frozen-training-report.json')
shutil.copyfile(base / 'factory-calibration-20261013/raw-intrinsics.json', root / 'frozen-intrinsics.json')
candidate_hash = hashlib.sha256((root / 'frozen-candidate.npz').read_bytes()).hexdigest()
assert candidate_hash == '819d0befaabe1973d299107b0a181e6ec93853a641840e3c9da04e1c84d4732b'
shutil.copyfile(Path(__file__), root / 'capture-used.py')
transaction = dict(session=session_name, seconds=args.seconds, candidate_frozen_before_new_capture=True,
    frozen_candidate_sha256=candidate_hash, fit_or_update_candidate_allowed=False,
    input_source='RTSP/TCP HEVC Main10 decoded on Windows; NOT sensor RAW',
    geometry='Displayed left half=cam0/right 0x32; right half=cam1/left 0x30. Undo horizontal mirror independently per eye.',
    timestamps='Encoded stream PTS and Windows receive clock; not V4L2 receiver or exposure time',
    RTSP_server_paused=False, sensor_controls_modified=False)
(root / 'transaction.json').write_text(json.dumps(transaction, indent=2) + '\n')
pending = queue.Queue(maxsize=8)
storage_error = []
records = []

def writer():
    try:
        while True:
            item = pending.get()
            if item is None:
                return
            sequence, pts_ns, receive_ns, image = item
            for eye in (0, 1):
                crop = ImageOps.mirror(image.crop((eye*1088, 0, (eye+1)*1088, 1280)))
                name = f'cam{eye}/{pts_ns}-{sequence}.png'
                crop.save(session / name, compress_level=1)
                records.append([sequence, eye, sequence, 0, pts_ns, receive_ns, 1088, 1280, 1088, name])
    except BaseException as error:
        storage_error.append(repr(error))

worker = threading.Thread(target=writer, name='owned-png-storage')
worker.start()
decoded = saved_pairs = 0
capture_first_pts = last_pts = None
first_wall = None
error = None
print(f'RTSP_REMAINS_ACTIVE_WARMUP_{args.warmup}_SECONDS', flush=True)
try:
    with av.open('rtsp://192.168.137.226:8554/stereo', options={'rtsp_transport': 'tcp'}, timeout=(8, 8)) as container:
        stream = container.streams.video[0]
        stream.thread_type = 'AUTO'
        warmup = time.monotonic() + args.warmup
        for frame in container.decode(stream):
            if frame.pts is None:
                continue
            assert (frame.width, frame.height) == (2176, 1280)
            if time.monotonic() < warmup:
                continue
            pts_ns = int(frame.pts * frame.time_base * 1_000_000_000)
            if capture_first_pts is None:
                capture_first_pts = pts_ns
                first_wall = time.monotonic()
                print(f'RECORDING_{args.seconds}_SECONDS_WITH_LIVE_PREVIEW', flush=True)
            last_pts = pts_ns
            if storage_error:
                raise RuntimeError(storage_error)
            if decoded % 12 == 0:
                pending.put_nowait((decoded, pts_ns, time.monotonic_ns(), frame.to_image().convert('L')))
                saved_pairs += 1
            decoded += 1
            if decoded % 600 == 0:
                print(json.dumps(dict(recorded_pts_seconds=(pts_ns-capture_first_pts)/1e9,
                     wall_seconds=time.monotonic()-first_wall, saved_pairs=saved_pairs)), flush=True)
            if pts_ns - capture_first_pts >= args.seconds * 1_000_000_000:
                break
            if time.monotonic() - first_wall > args.seconds + 25:
                raise RuntimeError('Decoder fell behind: stop without claiming a real-time capture')
except BaseException as problem:
    error = repr(problem)
finally:
    # Never lose ownership of the writer; no hardware or RTSP-service lifecycle operations exist here.
    if worker.is_alive():
        pending.put(None)
    worker.join()
    with (session / 'camera-frames.csv').open('w', newline='') as stream:
        output = csv.writer(stream)
        output.writerow(['pair_id','eye','decoded_sequence','unused_flags','stream_pts_ns','windows_receive_monotonic_ns','width','height','stride','image'])
        output.writerows(records)
    transaction.update(status='completed' if error is None and not storage_error else 'failed_partial_data_retained',
        error=error, storage_error=storage_error, decoded_frames=decoded,
        saved_pairs=len(records)//2, pts_duration_seconds=(last_pts-capture_first_pts)/1e9 if last_pts else 0,
        wall_seconds=time.monotonic()-first_wall if first_wall else 0,
        candidate_unchanged=candidate_hash == hashlib.sha256((root / 'frozen-candidate.npz').read_bytes()).hexdigest())
    (root / 'transaction.json').write_text(json.dumps(transaction, indent=2) + '\n')
print(json.dumps(transaction), flush=True)
if error or storage_error:
    raise SystemExit(1)
