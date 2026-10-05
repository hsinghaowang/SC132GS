#!/usr/bin/env python3
"""Replace one FDT in Qualcomm's concatenated combined-dtb container."""

import argparse
import hashlib
import pathlib
import struct


FDT_MAGIC = bytes.fromhex("d00dfeed")


def entries(data: bytes) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    offset = 0
    while offset < len(data):
        if data[offset : offset + 4] != FDT_MAGIC:
            raise ValueError(f"invalid FDT magic at offset 0x{offset:x}")
        if offset + 8 > len(data):
            raise ValueError("truncated FDT header")
        size = struct.unpack(">I", data[offset + 4 : offset + 8])[0]
        if size < 40 or offset + size > len(data):
            raise ValueError(f"invalid FDT size {size} at offset 0x{offset:x}")
        result.append((offset, size))
        offset += size
    return result


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=pathlib.Path)
    parser.add_argument("index", type=int)
    parser.add_argument("replacement", type=pathlib.Path)
    parser.add_argument("output", type=pathlib.Path)
    args = parser.parse_args()

    original = args.input.read_bytes()
    original_entries = entries(original)
    if not 0 <= args.index < len(original_entries):
        raise ValueError(f"index {args.index} outside 0..{len(original_entries) - 1}")

    replacement = args.replacement.read_bytes()
    if entries(replacement) != [(0, len(replacement))]:
        raise ValueError("replacement must contain exactly one complete FDT")

    chunks = [
        original[offset : offset + size]
        for offset, size in original_entries
    ]
    old_hash = digest(chunks[args.index])
    chunks[args.index] = replacement
    rebuilt = b"".join(chunks)
    args.output.write_bytes(rebuilt)

    rebuilt_entries = entries(rebuilt)
    if len(rebuilt_entries) != len(original_entries):
        raise AssertionError("entry count changed")
    for index, ((old_offset, old_size), (new_offset, new_size)) in enumerate(
        zip(original_entries, rebuilt_entries, strict=True)
    ):
        old_chunk = original[old_offset : old_offset + old_size]
        new_chunk = rebuilt[new_offset : new_offset + new_size]
        if index != args.index and digest(old_chunk) != digest(new_chunk):
            raise AssertionError(f"unmodified entry {index} changed")

    print(f"entries={len(rebuilt_entries)}")
    print(f"replaced_index={args.index}")
    print(f"old_sha256={old_hash}")
    print(f"new_sha256={digest(replacement)}")
    print(f"container_sha256={digest(rebuilt)}")
    print(f"container_size={len(rebuilt)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
