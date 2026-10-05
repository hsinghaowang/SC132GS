#!/usr/bin/env python3
"""Convert one tightly packed MIPI RAW10 monochrome frame to an 8-bit PNG."""

from __future__ import annotations

import argparse
import binascii
import pathlib
import struct
import zlib


def png_chunk(name: bytes, payload: bytes) -> bytes:
    body = name + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", binascii.crc32(body) & 0xFFFFFFFF)


def percentile(histogram: list[int], count: int, fraction: float) -> int:
    target = int((count - 1) * fraction)
    running = 0
    for value, occurrences in enumerate(histogram):
        running += occurrences
        if running > target:
            return value
    return len(histogram) - 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=pathlib.Path)
    parser.add_argument("output", type=pathlib.Path)
    parser.add_argument("--width", type=int, default=1088)
    parser.add_argument("--height", type=int, default=1280)
    parser.add_argument("--low-percentile", type=float, default=0.005)
    parser.add_argument("--high-percentile", type=float, default=0.995)
    args = parser.parse_args()

    packed = args.input.read_bytes()
    expected = args.width * args.height * 10 // 8
    if len(packed) != expected or args.width % 4:
        raise ValueError(f"expected {expected} RAW10 bytes, got {len(packed)}")

    pixels = [0] * (args.width * args.height)
    histogram = [0] * 1024
    destination = 0
    for source in range(0, len(packed), 5):
        low = packed[source + 4]
        values = (
            (packed[source] << 2) | (low & 0x03),
            (packed[source + 1] << 2) | ((low >> 2) & 0x03),
            (packed[source + 2] << 2) | ((low >> 4) & 0x03),
            (packed[source + 3] << 2) | ((low >> 6) & 0x03),
        )
        pixels[destination : destination + 4] = values
        destination += 4
        for value in values:
            histogram[value] += 1

    low = percentile(histogram, len(pixels), args.low_percentile)
    high = percentile(histogram, len(pixels), args.high_percentile)
    if high <= low:
        low, high = 0, 1023

    rows = bytearray()
    scale = 255.0 / (high - low)
    for y in range(args.height):
        rows.append(0)  # PNG filter type: None
        start = y * args.width
        for value in pixels[start : start + args.width]:
            rows.append(max(0, min(255, round((value - low) * scale))))

    header = struct.pack(">IIBBBBB", args.width, args.height, 8, 0, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", header)
    png += png_chunk(b"IDAT", zlib.compress(bytes(rows), 9))
    png += png_chunk(b"IEND", b"")
    args.output.write_bytes(png)
    print(f"pixels={len(pixels)} raw_min={next(i for i,v in enumerate(histogram) if v)} "
          f"raw_max={next(i for i,v in enumerate(reversed(histogram)) if v) ^ 1023} "
          f"display_low={low} display_high={high} png_bytes={len(png)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
