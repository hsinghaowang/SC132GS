#!/usr/bin/env python3
"""Measure actual decoded RTSP frames and retain one RGB image."""
import argparse
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
from gi.repository import Gst, GstApp  # noqa: F401: registers appsink methods


def chunk(name, data):
    body = name + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", binascii.crc32(body) & 0xffffffff)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--decoder", choices=("hardware", "software"), default="hardware")
    parser.add_argument("--minimum-frames",type=int,default=31)
    parser.add_argument("--stop-after-minimum", action="store_true",
                        help="Bound startup decoding; this does not prove sustained decoded FPS")
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    if args.minimum_frames < 3: parser.error('minimum frames must be >=3')
    args.output.mkdir(parents=True, exist_ok=True)
    Gst.init(None)
    decoder = "v4l2h265dec" if args.decoder == "hardware" else "avdec_h265"
    pipeline = Gst.parse_launch(
        f'rtspsrc location="{args.url}" protocols=tcp latency=100 ! '
        f'rtph265depay ! h265parse ! {decoder} ! videoconvert ! '
        'video/x-raw,format=RGB ! appsink name=frames sync=false max-buffers=4 drop=false')
    sink = pipeline.get_by_name("frames")
    bus = pipeline.get_bus()
    hashes = set()
    count = 0
    width = height = 0
    snapshot_channel_ranges = None
    snapshot_luma_statistics = None
    first_wall = first_pts = last_pts = None
    try:
        if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("decoder did not start")
        deadline = time.monotonic() + args.seconds
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
            if len(pixels) != width * height * 3:
                raise RuntimeError("RGB sample has unexpected stride/size")
            hashes.add(hashlib.sha256(pixels).hexdigest())
            if not count:
                first_wall, first_pts = time.monotonic(), buffer.pts
            if count == min(30,args.minimum_frames-1):
                snapshot_channel_ranges = [max(pixels[c::3])-min(pixels[c::3]) for c in range(3)]
                # Both eyes' central 80% ROI; this stream is grayscale RGB.
                eye_width = width // 2
                values = sorted(pixels[(y*width+x)*3]
                                for eye in range(2)
                                for y in range(height//10, height*9//10, 4)
                                for x in range(eye*eye_width+eye_width//10,
                                               eye*eye_width+eye_width*9//10, 4))
                snapshot_luma_statistics = dict(
                    sampled_pixels=len(values), mean=sum(values)/len(values),
                    median=values[len(values)//2], p10=values[len(values)//10],
                    p90=values[len(values)*9//10],
                    dark_fraction=sum(v<=5 for v in values)/len(values),
                    bright_fraction=sum(v>=250 for v in values)/len(values))
                rows = b"".join(b"\0" + pixels[y*width*3:(y+1)*width*3] for y in range(height))
                png = b"\x89PNG\r\n\x1a\n"
                png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                png += chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")
                (args.output / "decoded.png").write_bytes(png)
            last_pts = buffer.pts
            count += 1
            if args.stop_after_minimum and count >= args.minimum_frames:
                break
        elapsed = time.monotonic() - first_wall if first_wall else 0
        pts_span = (last_pts-first_pts)/Gst.SECOND if count else 0
        result = dict(decoder=args.decoder, bounded_decode=args.stop_after_minimum,
                      decoded_frames=count, unique_rgb_hashes=len(hashes),
                      snapshot_channel_ranges=snapshot_channel_ranges,
                      snapshot_luma_statistics=snapshot_luma_statistics,
                      snapshot_has_spatial_detail=bool(snapshot_channel_ranges and max(snapshot_channel_ranges) >= 2),
                      width=width, height=height, wall_seconds=elapsed,
                      wall_fps=(count-1)/elapsed if elapsed else 0,
                      pts_fps=(count-1)/pts_span if pts_span else 0)
        (args.output / "decode.json").write_text(json.dumps(result, indent=2)+"\n")
        print(json.dumps(result))
        # Changing hashes alone can still describe a uniform green decoder output.
        # This content check rejects flat output; inspect decoded.png for scene proof.
        return 0 if count >= args.minimum_frames and len(hashes) >= 2 and result['snapshot_has_spatial_detail'] else 1
    finally:
        pipeline.set_state(Gst.State.NULL)


if __name__ == "__main__":
    raise SystemExit(main())
