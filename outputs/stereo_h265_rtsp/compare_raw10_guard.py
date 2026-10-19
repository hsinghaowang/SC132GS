#!/usr/bin/env python3
"""Compare sensor-generated patterns byte-for-byte across RAW10 receive paths."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time

parser = argparse.ArgumentParser()
parser.add_argument('output', type=Path)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=False)
FRAME_BYTES = 1360 * 1280
ROOT = Path('/sys/module/qcom_camss/parameters')

def run(*argv):
    return subprocess.check_output(argv, text=True, timeout=15).strip()

def reg(bus, address, high, low, value=None):
    tail = ['r1'] if value is None else [hex(value)]
    return run('i2ctransfer', '-f', '-y', str(bus),
               f'w{2 if value is None else 3}@{address}', hex(high), hex(low), *tail)

def frame(process):
    deadline = time.monotonic()+5
    data = bytearray()
    with selectors.DefaultSelector() as ready:
        ready.register(process.stdout, selectors.EVENT_READ)
        while len(data) < FRAME_BYTES:
            if not ready.select(max(0, deadline-time.monotonic())):
                raise RuntimeError('RAW10 frame timeout')
            chunk = os.read(process.stdout.fileno(), min(65536, FRAME_BYTES-len(data)))
            if not chunk:
                raise RuntimeError('RAW10 stream ended')
            data.extend(chunk)
    return bytes(data)

def stop(process):
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

original_guard = (ROOT/'geometry_guard').read_text()
restore_service = any(subprocess.run(['systemctl', 'is-active', '--quiet', name]).returncode == 0
                      for name in ('sc132gs-camera-restore.service', 'sc132gs-camera-rtsp.service'))
results = []
try:
    run('systemctl', 'stop', 'sc132gs-camera-restore.service')
    run('systemctl', 'stop', 'sc132gs-camera-rtsp.service')
    for role, bus, address, client in [('cam0',18,'0x32','18-0032'), ('cam1',16,'0x30','16-0030')]:
        node = run('sc132gs-discover', role)
        for pattern in (0,):
            reference = None
            for guard in (0, 1):
                folder = args.output/f'{role}-pattern{pattern}-guard{guard}'
                folder.mkdir()
                (ROOT/'geometry_guard').write_text(str(guard))
                run('prepare-sc132gs-sync-gpios')
                generator = capture = None
                previous = None
                with (folder/'fsync.log').open('w') as gpio_log, (folder/'capture.log').open('w') as capture_log:
                    try:
                        generator = subprocess.Popen(['sc132gs-fsync-generator','auto','18','19','60','100','active-low'], stdout=gpio_log, stderr=subprocess.STDOUT)
                        for _ in range(100):
                            if 'FSYNC generator armed' in (folder/'fsync.log').read_text(): break
                            time.sleep(.01)
                        else: raise RuntimeError('FSYNC did not arm')
                        capture = subprocess.Popen(['v4l2-ctl','-d',node,'--stream-mmap=8','--stream-to=-'], stdout=subprocess.PIPE, stderr=capture_log)
                        time.sleep(.3)
                        Path(f'/sys/bus/i2c/devices/{client}/trigger_60fps').write_text('1')
                        generator.send_signal(signal.SIGUSR1)
                        frame(capture)
                        previous = int(reg(bus,address,0x45,0x01),16)
                        # Rockchip's SC132GS enable/disable values differ by
                        # bit 3. Preserve this board's other register bits.
                        requested = previous | 0x08
                        reg(bus,address,0x45,0x01,requested)
                        for _ in range(12): frame(capture)
                        frames = [frame(capture) for _ in range(3)]
                        for index, data in enumerate(frames):
                            (folder/f'frame{index}.raw10').write_bytes(data)
                        (folder/'pattern-register.json').write_text(json.dumps(dict(
                            before=previous,requested=requested,
                            readback=reg(bus,address,0x45,0x01))))
                        hashes = [hashlib.sha256(data).hexdigest() for data in frames]
                        stable = len(set(hashes)) == 1
                        (folder/'frame.raw10').write_bytes(frames[0])
                        if guard == 0: reference = frames
                        identical = reference == frames
                        if not identical: raise RuntimeError(f'RAW10 bytes changed: {role} pattern {pattern}')
                        entry = dict(role=role,pattern=pattern,guard=guard,bytes=FRAME_BYTES,
                                     stable_three_frames=stable,identical_to_reference=identical,sha256=hashes)
                        results.append(entry)
                        print(json.dumps(entry), flush=True)
                    finally:
                        if previous is not None:
                            reg(bus,address,0x45,0x01,previous)
                        stop(capture)
                        stop(generator)
    (args.output/'result.json').write_text(json.dumps(dict(passed=True,cases=results),indent=2))
finally:
    (ROOT/'geometry_guard').write_text(original_guard)
    if restore_service:
        run('systemctl', 'start', 'sc132gs-camera-restore.service')
        (args.output/'status-restored.txt').write_text(run('sc132gs-camera', 'status')+'\n')
