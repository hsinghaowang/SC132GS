#!/usr/bin/env python3
"""Read-only CSID0/1 RDI0 counters on the active QCS6490 camera topology."""
import json
import mmap
import os
import struct
import subprocess
import time
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('--csid', type=int, choices=(0, 1))
parser.add_argument('--capture-pid', type=int)
args = parser.parse_args()
if args.capture_pid is not None:
    assert args.csid is not None
    from pathlib import Path
    handles = Path(f'/proc/{args.capture_pid}/fd')
    assert any(os.readlink(fd).startswith('/dev/video') for fd in handles.iterdir())
else:
    subprocess.run(['systemctl', 'is-active', '--quiet', 'sc132gs-camera-rtsp.service'], check=True)
with open('/dev/mem', 'rb', buffering=0) as memory:
    bases = (0x0acb3000, 0x0acba000)
    for base in (bases[args.csid],) if args.csid is not None else bases:
        with mmap.mmap(memory.fileno(), 4096, access=mmap.ACCESS_READ, offset=base) as registers:
            values = {hex(offset): hex(struct.unpack_from('<I', registers, offset)[0])
                      for offset in (0, 0x40, 0x44, 0x300, 0x304, 0x308, 0x31c, 0x320,
                                     0x370, 0x374, 0x378, 0x37c, 0x380, 0x3e0, 0x3e4)}
            print(json.dumps(dict(monotonic_ns=time.monotonic_ns(), csid_base=hex(base), registers=values)))
