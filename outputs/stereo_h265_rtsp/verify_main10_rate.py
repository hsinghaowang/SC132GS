#!/usr/bin/env python3
"""Measure decoded Main10 without an intermediate eight-bit conversion."""
import argparse
import hashlib
import json
import pathlib
import time
import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstApp', '1.0')
from gi.repository import Gst, GstApp

p = argparse.ArgumentParser()
p.add_argument('url')
p.add_argument('--seconds', type=float, default=300)
p.add_argument('--output', type=pathlib.Path, required=True)
a = p.parse_args()
a.output.mkdir(parents=True, exist_ok=True)
Gst.init(None)
pipe = Gst.parse_launch(f'rtspsrc location="{a.url}" protocols=tcp latency=100 ! rtph265depay ! h265parse ! avdec_h265 ! appsink name=frames sync=false max-buffers=8 drop=false')
sink = pipe.get_by_name('frames')
bus = pipe.get_bus()
count = 0
first_wall = first_pts = last_pts = None
hashes = set()
gaps = 0
caps_text = ''
snapshot = {}
try:
    pipe.set_state(Gst.State.PLAYING)
    deadline = time.monotonic() + a.seconds + 15
    while time.monotonic() < deadline:
        err = bus.pop_filtered(Gst.MessageType.ERROR)
        if err:
            raise RuntimeError(err.parse_error())
        sample = sink.try_pull_sample(200 * Gst.MSECOND)
        if not sample:
            continue
        b = sample.get_buffer()
        caps = sample.get_caps().get_structure(0)
        if caps.get_value('format') != 'I420_10LE':
            raise RuntimeError(sample.get_caps().to_string())
        now = time.monotonic()
        if first_wall is None:
            first_wall, first_pts = now, b.pts
            deadline = now + a.seconds
            caps_text = sample.get_caps().to_string()
        if last_pts is not None and b.pts-last_pts > 25*Gst.MSECOND:
            gaps += 1
        last_pts = b.pts
        if count % 60 == 0:
            data = b.extract_dup(0, b.get_size())
            hashes.add(hashlib.sha256(data).hexdigest())
            if count == 60:
                import numpy as np
                w, h = caps.get_value('width'), caps.get_value('height')
                luma = np.frombuffer(data, dtype='<u2', count=w*h).reshape(h,w)
                snapshot = dict(min=int(luma.min()), max=int(luma.max()), unique_levels=int(np.unique(luma).size), low_bits_present=bool(np.any(luma % 4)))
                (a.output/'decoded-luma10.u16le').write_bytes(luma.tobytes())
        count += 1
    elapsed = time.monotonic()-first_wall if first_wall else 0
    span = (last_pts-first_pts)/Gst.SECOND if count else 0
    result = dict(caps=caps_text, decoded_frames=count, wall_seconds=elapsed, wall_fps=(count-1)/elapsed if elapsed else 0, pts_fps=(count-1)/span if span else 0, pts_gaps_over_25ms=gaps, sampled_unique_hashes=len(hashes), snapshot=snapshot)
    (a.output/'decode.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result), flush=True)
    raise SystemExit(0 if count > a.seconds*59 and gaps == 0 and len(hashes)>1 else 1)
finally:
    pipe.set_state(Gst.State.NULL)
