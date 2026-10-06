#!/usr/bin/env python3
"""Decode the live HDR RTSP composite and retain pixels and frame evidence."""
import binascii
import hashlib
import json
import pathlib
import struct
import time
import zlib
import gi
gi.require_version("Gst", "1.0")
gi.require_version("GstApp", "1.0")
from gi.repository import Gst, GstApp  # Import registers the appsink methods.

Gst.init(None)
root = pathlib.Path(__file__).resolve().parent
pipeline = Gst.parse_launch(
    'rtspsrc location=rtsp://192.168.137.226:8554/stereo protocols=tcp latency=100 ! '
    'rtph265depay ! h265parse ! avdec_h265 ! videoconvert ! '
    'video/x-raw,format=RGB ! appsink name=frames sync=false max-buffers=4 drop=false')
sink = pipeline.get_by_name("frames")
bus = pipeline.get_bus()
assert pipeline.set_state(Gst.State.PLAYING) != Gst.StateChangeReturn.FAILURE
hashes = set()
count = 0
first_wall = first_pts = last_pts = None
deadline = time.monotonic() + 10

def chunk(name, data):
    body = name + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", binascii.crc32(body) & 0xffffffff)

try:
    while time.monotonic() < deadline:
        error = bus.pop_filtered(Gst.MessageType.ERROR)
        if error:
            raise RuntimeError(error.parse_error())
        sample = sink.try_pull_sample(200 * Gst.MSECOND)
        if not sample:
            continue
        buffer = sample.get_buffer()
        pixels = buffer.extract_dup(0, buffer.get_size())
        caps = sample.get_caps().get_structure(0)
        width, height = caps.get_value("width"), caps.get_value("height")
        assert (width, height) == (2176, 1280)
        assert len(pixels) == width * height * 3
        hashes.add(hashlib.sha256(pixels).hexdigest())
        if count == 0:
            first_wall = time.monotonic()
            first_pts = buffer.pts
        if count == 30:
            rows = b"".join(b"\0" + pixels[y*width*3:(y+1)*width*3] for y in range(height))
            png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            png += chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")
            (root / "hdr-stereo-decoded.png").write_bytes(png)
        last_pts = buffer.pts
        count += 1
    elapsed = time.monotonic() - first_wall if first_wall else 0
    result = dict(decoded_frames=count, unique_rgb_hashes=len(hashes), width=2176, height=1280,
                  wall_seconds=elapsed, fps=(count-1)/elapsed if elapsed else 0,
                  pts_span_seconds=(last_pts-first_pts)/Gst.SECOND if count else 0)
    (root / "decode-evidence.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    assert count >= 200 and len(hashes) >= 2
finally:
    pipeline.set_state(Gst.State.NULL)
