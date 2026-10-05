#!/usr/bin/env python3
"""Count loopback RTSP access units or decoded frames without saving pixels."""

import argparse
import time

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstApp", "1.0")
from gi.repository import Gst, GstApp  # noqa: E402,F401


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="rtsp://127.0.0.1:8554/stereo")
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--decode", action="store_true")
    args = parser.parse_args()
    Gst.init(None)
    decode = "v4l2h265dec ! " if args.decode else ""
    pipeline = Gst.parse_launch(
        f'rtspsrc location="{args.url}" protocols=tcp latency=100 ! '
        "rtph265depay ! h265parse ! " + decode +
        "appsink name=counter sync=false max-buffers=4 drop=false"
    )
    sink = pipeline.get_by_name("counter")
    bus = pipeline.get_bus()
    if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
        raise RuntimeError("RTSP pipeline could not enter PLAYING")
    count = 0
    first_wall = None
    first_pts = None
    last_pts = None
    deadline = time.monotonic() + args.seconds
    try:
        while time.monotonic() < deadline:
            message = bus.pop_filtered(Gst.MessageType.ERROR)
            if message:
                error, debug = message.parse_error()
                raise RuntimeError(f"{error.message}: {debug}")
            sample = sink.try_pull_sample(200 * Gst.MSECOND)
            if sample is None:
                continue
            pts = sample.get_buffer().pts
            if first_wall is None:
                first_wall, first_pts = time.monotonic(), pts
            last_pts = pts
            count += 1
        elapsed = time.monotonic() - first_wall if first_wall else 0.0
        print(
            f"mode={'decoded' if args.decode else 'H265_AU'} "
            f"frames={count} wall_s={elapsed:.3f} "
            f"fps={((count - 1) / elapsed if elapsed > 0 else 0):.2f} "
            f"pts_span_s={((last_pts - first_pts) / Gst.SECOND if count > 1 else 0):.3f}"
        )
        return 0 if count >= max(1, (args.seconds - 2) * 28) else 1
    finally:
        pipeline.set_state(Gst.State.NULL)


if __name__ == "__main__":
    raise SystemExit(main())
