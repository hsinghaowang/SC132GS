#!/usr/bin/env python3
"""Prepare the existing boot DTB container; never flash a partition."""
import hashlib
import pathlib
import struct
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent
original = (ROOT / "combined-dtb-before.dtb").read_bytes()
entries = []
offset = 0
while offset < len(original):
    assert original[offset:offset + 4] == bytes.fromhex("d00dfeed")
    size = struct.unpack_from(">I", original, offset + 4)[0]
    assert size >= 40 and offset + size <= len(original)
    entries.append(original[offset:offset + size])
    offset += size

def get(file, node, prop):
    return subprocess.check_output(["fdtget", str(file), node, prop], text=True).strip()

live = pathlib.Path("/sys/firmware/fdt")
matches = []
for index, data in enumerate(entries):
    file = ROOT / f"entry-{index}.dtb"
    file.write_bytes(data)
    if all(get(file, "/", prop) == get(live, "/", prop)
           for prop in ("model", "compatible", "qcom,board-id", "qcom,msm-id")):
        matches.append((index, file))
assert len(matches) == 1, matches
index, file = matches[0]
nodes = [
    "/soc@0/cci@ac4b000/i2c-bus@0/camera@32/port/endpoint",
    "/soc@0/cci@ac4a000/i2c-bus@0/camera@30/port/endpoint",
    "/soc@0/camss@acaf000/ports/port@1/endpoint",
    "/soc@0/camss@acaf000/ports/port@4/endpoint",
]
for node in nodes:
    assert get(file, node, "data-lanes") == "0"
    assert get(file, node, "clock-lanes") == "7"
    subprocess.run(["fdtput", "-t", "i", str(file), node, "data-lanes", "0", "1"], check=True)
    assert get(file, node, "data-lanes") == "0 1"
entries[index] = file.read_bytes()
output = ROOT / "combined-dtb-hdr-2lane.dtb"
output.write_bytes(b"".join(entries))
subprocess.run(["dtc", "-I", "dtb", "-O", "dts", "-o", str(ROOT / "hdr-2lane.dts"), str(file)], check=True, stderr=subprocess.DEVNULL)
print(f"Matched current board entry {index}; changed only four data-lanes properties to <0 1>.")
for path in (ROOT / "combined-dtb-before.dtb", output):
    print(path.name, len(path.read_bytes()), hashlib.sha256(path.read_bytes()).hexdigest())
