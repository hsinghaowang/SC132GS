import json
from pathlib import Path
import time
import av

root = Path(__file__).resolve().parent / 'rtsp-30fps-10mbps-20261014'
root.mkdir(exist_ok=True)
frames = 0
first_pts = last_pts = None
snapshot = None
began = time.monotonic()
with av.open('rtsp://192.168.137.226:8554/stereo', options={'rtsp_transport':'tcp'}, timeout=(8,8)) as container:
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
        if frames == 30:
            snapshot = frame.to_image()
        if last_pts - first_pts >= 8:
            break
        if time.monotonic() - began > 20:
            raise RuntimeError('Decoded stream did not sustain the observation window')
fps = (frames-1)/(last_pts-first_pts)
assert snapshot is not None
snapshot.save(root / 'decoded.png')
proof = dict(status='passed' if abs(fps-30)<.6 and (frame.width,frame.height)==(2176,1280) else 'failed',
    decoded_frames=frames, pts_fps=fps, width=frame.width, height=frame.height,
    format=frame.format.name, observation_pts_seconds=last_pts-first_pts,
    wall_seconds=time.monotonic()-began, configured_target_bitrate_bits_per_second=10000000)
(root / 'decode.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(proof))
raise SystemExit(0 if proof['status']=='passed' else 1)
