#!/usr/bin/env python3
"""Read-only source/binary identity check; optionally verify the live IMU executable inode."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

ROOT = Path('/home/ubuntu/sc132gs-stability-20261015')
CLIENT = Path('/home/ubuntu/capture-api-20261015')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-imu-pid', type=int)
    parser.add_argument('--output', type=Path, default=ROOT / 'client-source-check.json')
    args = parser.parse_args()
    manifest = json.loads((ROOT / 'client-inputs.json').read_text())
    checks = {}
    for group in ('source_sha256', 'binary_sha256'):
        checks[group] = {name: sha(CLIENT / name) == expected for name, expected in manifest[group].items()}
    live = None
    if args.live_imu_pid:
        current = Path(f'/proc/{args.live_imu_pid}/exe')
        target = CLIENT / 'build-imu/gs130wi-imu'
        a, b = current.stat(), target.stat()
        live = dict(pid=args.live_imu_pid, executable=str(current.resolve()),
            same_inode=(a.st_dev, a.st_ino) == (b.st_dev, b.st_ino), sha256=sha(current))
        checks['live_imu'] = dict(same_inode=live['same_inode'],
            expected_binary=live['sha256'] == manifest['binary_sha256']['build-imu/gs130wi-imu'])
    passed = all(all(group.values()) for group in checks.values())
    report = dict(passed=passed, observed_monotonic_ns=time.monotonic_ns(), checks=checks, live_imu=live,
        input_manifest_sha256=sha(ROOT / 'client-inputs.json'),
        expected_changes_since_api_build=manifest['expected_changes_since_api_build'],
        scope='Source files and binary identity, with optional live executable inode; runtime acceptance is separate')
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(passed=passed, sources=len(checks['source_sha256']), binaries=len(checks['binary_sha256']), live_imu=live)))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
