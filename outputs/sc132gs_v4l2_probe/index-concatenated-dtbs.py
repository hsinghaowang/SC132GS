#!/usr/bin/env python3
import pathlib
import struct
import subprocess
import sys
import tempfile


def get_property(path: str, name: str) -> str:
    result = subprocess.run(
        ["fdtget", path, "/", name],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "-"


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} COMBINED_DTB", file=sys.stderr)
        return 2

    data = pathlib.Path(sys.argv[1]).read_bytes()
    offset = 0
    index = 0
    while True:
        offset = data.find(bytes.fromhex("d00dfeed"), offset)
        if offset < 0:
            break
        if offset + 8 > len(data):
            break

        size = struct.unpack(">I", data[offset + 4 : offset + 8])[0]
        if 40 <= size <= len(data) - offset:
            with tempfile.NamedTemporaryFile(suffix=".dtb") as item:
                item.write(data[offset : offset + size])
                item.flush()
                model = get_property(item.name, "model")
                compatible = get_property(item.name, "compatible")
                board_id = get_property(item.name, "qcom,board-id")
                msm_id = get_property(item.name, "qcom,msm-id")
            print(
                f"{index:02d} off=0x{offset:x} size={size} "
                f"model={model} | compatible={compatible} | "
                f"board-id={board_id} | msm-id={msm_id}"
            )
            index += 1
        offset += 4

    print(f"count={index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
