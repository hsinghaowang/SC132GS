#!/usr/bin/env python3
"""Retain a short RTSP clip and decoded samples for manual motion inspection."""
import json
import pathlib
import sys
import time
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst
from verify_decode_rate import chunk
import struct
import zlib

out = pathlib.Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
Gst.init(None)
pipeline = Gst.parse_launch(
    'rtspsrc location=rtsp://192.168.137.226:8554/stereo protocols=tcp latency=100 ! '
    'rtph265depay ! h265parse ! tee name=t '
    f't. ! queue ! matroskamux ! filesink location="{out}/motion.mkv" '
    't. ! queue ! avdec_h265 ! videoconvert ! video/x-raw,format=RGB ! '
    'appsink name=frames sync=false max-buffers=4 drop=false wait-on-eos=false')
sink = pipeline.get_by_name('frames')
bus = pipeline.get_bus()
count = 0
first_pts = last_pts = None
deadline = time.monotonic() + 35
started = None
try:
    pipeline.set_state(Gst.State.PLAYING)
    while time.monotonic() < deadline:
        error = bus.pop_filtered(Gst.MessageType.ERROR)
        if error:
            raise RuntimeError(error.parse_error())
        sample = sink.emit('try-pull-sample', 200 * Gst.MSECOND)
        if sample is None:
            continue
        buffer = sample.get_buffer()
        if started is None:
            started = time.monotonic()
            deadline = started + 25
            first_pts = buffer.pts
            (out / 'ready').write_text('recording\n')
            print('RECORDING', flush=True)
        last_pts = buffer.pts
        if count % 3 == 0:
            caps = sample.get_caps().get_structure(0)
            width, height = caps.get_value('width'), caps.get_value('height')
            pixels = buffer.extract_dup(0, buffer.get_size())
            if len(pixels) != width * height * 3:
                raise RuntimeError('Unexpected RGB stride')
            rows = b''.join(b'\0' + pixels[y*width*3:(y+1)*width*3] for y in range(height))
            png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            png += chunk(b'IDAT', zlib.compress(rows, 1)) + chunk(b'IEND', b'')
            (out / f'frame-{count:04d}.png').write_bytes(png)
        count += 1
    if count < 60:
        raise RuntimeError('Insufficient decoded frames')
    pipeline.send_event(Gst.Event.new_eos())
    message = bus.timed_pop_filtered(5*Gst.SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
    if message is None or message.type != Gst.MessageType.EOS:
        raise RuntimeError('Recording did not finalize')
    result = dict(decoded_frames=count, pts_fps=(count-1)/((last_pts-first_pts)/Gst.SECOND),
                  sampled_every_frames=3, recording_seconds=time.monotonic()-started)
    (out / 'result.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)
finally:
    pipeline.set_state(Gst.State.NULL)
