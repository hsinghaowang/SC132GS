"""Decode on the viewer PC so verification does not load the capture board."""
import argparse
import hashlib
import json
from pathlib import Path
import time

import av

parser = argparse.ArgumentParser()
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
frames = 0
hashes = set()
first_pts = last_pts = None
snapshot = None
started = time.monotonic()
with av.open('rtsp://192.168.137.226:8554/stereo',
             options={'rtsp_transport': 'tcp'}, timeout=(8, 8)) as container:
    stream = container.streams.video[0]
    stream.thread_type = 'AUTO'
    for frame in container.decode(stream):
        if frame.pts is None:
            continue
        frames += 1
        timestamp = float(frame.pts * frame.time_base)
        if first_pts is None:
            first_pts = timestamp
        last_pts = timestamp
        if frames % 30 == 0:
            pixels = frame.to_image()
            hashes.add(hashlib.sha256(pixels.tobytes()).hexdigest())
            if snapshot is None:
                snapshot = pixels
        if last_pts - first_pts >= 8:
            break
elapsed = time.monotonic() - started
fps = (frames - 1) / (last_pts - first_pts)
extrema = snapshot.getextrema() if snapshot else ()
proof = dict(viewer='Windows/PyAV', codec='HEVC', decoded_frames=frames,
             width=frame.width, height=frame.height, format=frame.format.name,
             pts_fps=fps, wall_seconds=elapsed, sampled_unique_frames=len(hashes),
             channel_extrema=extrema)
proof['passed'] = (abs(fps - 60) < 1.5 and (frame.width, frame.height) == (2176, 1280)
                   and len(hashes) > 1 and max(high - low for low, high in extrema) > 32)
snapshot.save(args.output / 'decoded.png')
(args.output / 'decode.json').write_text(json.dumps(proof, indent=2) + '\n')
print(json.dumps(proof))
raise SystemExit(0 if proof['passed'] else 1)
