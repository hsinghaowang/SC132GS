#!/usr/bin/env python3
"""Check actual SOF rates in stable exposure intervals, without trigger guesses."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--events', required=True, type=Path)
    parser.add_argument('--controls', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--fps', type=float, default=30.0)
    args = parser.parse_args()
    events_data = args.events.read_bytes()
    controls_data = args.controls.read_bytes()
    events = [list(map(int, line.split())) for line in events_data.decode().splitlines()
              if line.strip() and not line.startswith('#')]
    controls = controls_data.decode().splitlines()
    if not events or len(controls) % 3:
        raise ValueError('incomplete exposure profile')
    changes = []
    for index in range(0, len(controls), 3):
        rows = [int(controls[index + eye + 1].split(':')[1]) for eye in (0, 1)]
        if rows[0] != rows[1]:
            raise ValueError('exposure readback differs between eyes')
        changes.append((int(controls[index]), rows[0]))
    if len({event[1] for event in events}) != 1:
        raise ValueError('multiple sessions cannot form one rate profile')
    end_of_trace = max(event[4] for event in events)
    profiles = []
    for index, (start, rows) in enumerate(changes):
        end = changes[index + 1][0] if index + 1 < len(changes) else end_of_trace
        profile = {'rows': rows, 'eyes': {}}
        for eye in (0, 1):
            frames = [event for event in events if event[2] == 2 and event[3] == eye
                      and start + 2_000_000_000 <= event[4] < end - 1_000_000_000]
            monotonic = (len(frames) > 1 and all(
                a[4] < b[4] and a[6] < b[6] for a, b in zip(frames, frames[1:])))
            if not monotonic:
                raise ValueError('insufficient or non-monotonic hardware SOFs')
            hardware_span = (frames[-1][6] - frames[0][6]) / 19_200_000
            host_span = (frames[-1][4] - frames[0][4]) / 1e9
            hardware_fps = (len(frames) - 1) / hardware_span
            host_fps = (len(frames) - 1) / host_span
            intervals = [(b[6] - a[6]) * 1e9 / 19_200_000
                         for a, b in zip(frames, frames[1:])]
            profile['eyes'][str(eye)] = {
                'samples': len(frames), 'hardware_fps': hardware_fps,
                'host_fps': host_fps,
                'median_hardware_interval_ns': statistics.median(intervals),
                'within_requested_fps': (len(frames) >= 100 and
                    abs(hardware_fps / args.fps - 1) <= 0.01 and
                    abs(host_fps / args.fps - 1) <= 0.01)}
        profiles.append(profile)
    result = {
        'passed': bool(profiles) and all(eye['within_requested_fps']
            for profile in profiles for eye in profile['eyes'].values()),
        'requested_fps': args.fps, 'session': events[0][1],
        'profiles': profiles,
        'events_sha256': hashlib.sha256(events_data).hexdigest(),
        'controls_sha256': hashlib.sha256(controls_data).hexdigest(),
        'scope': 'recorded CSID hardware SOF rate; no trigger/exposure-start inference'}
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
