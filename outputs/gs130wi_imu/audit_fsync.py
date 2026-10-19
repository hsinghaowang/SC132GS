#!/usr/bin/env python3
"""Independently audit raw FIFO fields. Does not infer camera trigger identity."""
import argparse
import collections
import csv
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv', type=Path)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--after', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--expect-fsync', action='store_true')
    args = parser.parse_args()
    errors = []
    previous = None
    ticks = 0
    markers = 0
    previous_marker = None
    gaps = collections.Counter()
    samples = 0
    first_read = last_read = None
    with args.csv.open(newline='') as stream:
        for index, row in enumerate(csv.DictReader(stream)):
            samples += 1
            last_read = int(row['host_read_end_ns'])
            if first_read is None:
                first_read = last_read
            header = int(row['header']) & 0xfc
            raw = int(row['timestamp_raw'])
            if int(row['index']) != index or row['valid'] != '1':
                errors.append(f'invalid index/sample at {index}')
            if header == 0x6c:
                markers += 1
                if previous_marker is not None:
                    gaps[index - previous_marker] += 1
                previous_marker = index
                if row['sensor_time_valid'] != '0' or row['sensor_elapsed_ns']:
                    errors.append(f'FSYNC offset published as sample counter at {index}')
                if int(row['fsync_offset_ns']) != raw * 32000 // 30:
                    errors.append(f'wrong FSYNC conversion at {index}')
            elif header == 0x68:
                if row['sensor_time_valid'] != '1' or row['fsync_offset_ns']:
                    errors.append(f'normal counter mislabeled at {index}')
                if previous:
                    prev_index, prev_raw = previous
                    delta = (raw - prev_raw) % 65536
                    intervals = index - prev_index
                    if not 4000 * intervals <= delta <= 5500 * intervals:
                        errors.append(f'counter discontinuity at {index}')
                    ticks += delta
                if int(row['sensor_elapsed_ns']) != ticks * 32000 // 30:
                    errors.append(f'wrong counter accumulation at {index}')
                previous = index, raw
            else:
                errors.append(f'unsupported header at {index}')
    restored = json.loads(args.before.read_text()) == json.loads(args.after.read_text())
    if not restored:
        errors.append('register restoration mismatch')
    if not samples or (args.expect_fsync and markers < 2):
        errors.append('missing samples/FSYNC observations')
    if not args.expect_fsync and markers:
        errors.append('unexpected FSYNC observations in baseline')
    span = (last_read - first_read) / 1e9 if samples else 0
    report = {
        'passed': not errors, 'errors': errors, 'samples': samples,
        'host_read_span_s': span, 'fsync_marked_packets': markers,
        'fsync_packet_index_gaps': dict(gaps), 'adjacent_fsync_pairs': gaps[1],
        'registers_restored': restored,
        'frame_association_validated': False, 'host_sample_time_validated': False,
        'scope': 'FIFO field semantics/counter integrity/restoration only. Adjacent marked '
                 'packets remain separate raw observations; no deduplication or frame ID assigned.'}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
