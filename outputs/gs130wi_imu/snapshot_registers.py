#!/usr/bin/env python3
"""Read-only profile snapshot, with temporary bank selection restored in finally.

Run only while the IMU capture owner is stopped. Camera I2C addresses are untouched.
"""
import fcntl
import json
import subprocess


def transfer(*args):
    return subprocess.check_output(
        ['i2ctransfer', '-y', '18', *args], text=True).strip()


def read(reg):
    return int(transfer('w1@0x68', hex(reg), 'r1'), 16)


with open('/run/lock/gs130wi-imu-i2c-18-68.lock', 'a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if read(0x76) != 0:
        raise RuntimeError('expected bank 0; refusing to change unknown state')
    if read(0x4e) & 0x0f or read(0x16) & 0xc0:
        raise RuntimeError('IMU/FIFO active; refusing bank selection')
    regs = [0x14, 0x16, 0x4c, 0x4d, 0x4e, 0x4f, 0x50, 0x54,
            0x5f, 0x60, 0x61, 0x62, 0x63, 0x64, 0x65]
    result = {'bank0': {hex(reg): read(reg) for reg in regs}}
    try:
        transfer('w2@0x68', '0x76', '1')
        result['bank1'] = {'0x7b': read(0x7b)}
    finally:
        transfer('w2@0x68', '0x76', '0')
    result['bank_selector'] = read(0x76)
    print(json.dumps(result, indent=2))
