#!/usr/bin/env python3
"""Forward every Nth fixed-size RAW frame from stdin to stdout."""

from __future__ import annotations

import argparse
import sys


def read_exact(size: int) -> bytes | None:
    chunks = bytearray(size)
    view = memoryview(chunks)
    offset = 0
    while offset < size:
        count = sys.stdin.buffer.readinto(view[offset:])
        if not count:
            return None
        offset += count
    return chunks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("frame_bytes", type=int)
    parser.add_argument("step", type=int)
    args = parser.parse_args()
    if args.frame_bytes <= 0 or args.step <= 0:
        parser.error("frame_bytes and step must be positive")

    index = 0
    try:
        while (frame := read_exact(args.frame_bytes)) is not None:
            if index % args.step == 0:
                sys.stdout.buffer.write(frame)
                sys.stdout.buffer.flush()
            index += 1
    except BrokenPipeError:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
