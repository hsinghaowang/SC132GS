"""Summarize bounded capture/processing traces without inferring unobserved queue state."""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path


def distribution(values):
    values = sorted(values)
    return dict(count=len(values), mean_ms=sum(values) / len(values) / 1e6,
                p95_ms=values[max(0, math.ceil(len(values) * .95) - 1)] / 1e6,
                max_ms=values[-1] / 1e6)


def analyze(paths):
    result = {}
    for path in paths:
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        header, events = rows[0], rows[1:]
        timing, held, returned, snapshots, failures = defaultdict(list), {}, [], [], []
        for event in events:
            timing[f"{event['op']}:eye{event['eye']}"].append(event['end_ns'] - event['begin_ns'])
            key = event['eye'], event['index']
            if event['op'] == 'dqbuf' and not event['errno']:
                held[key] = event['end_ns']
            if event['op'] == 'qbuf' and not event['errno'] and key in held:
                returned.append(event['end_ns'] - held.pop(key))
            if event['op'] == 'buffer_snapshot':
                snapshots.append(dict(**event, queued=bool(event['flags'] & 2),
                                      done=bool(event['flags'] & 4), error=bool(event['flags'] & 64)))
            if event['errno']:
                failures.append(event)
        summary = dict(header=header, stage_timing={key: distribution(values) for key, values in timing.items()},
                       syscall_failures=failures, buffer_snapshots=snapshots,
                       unmatched_dequeues_in_retained_window=len(held))
        if returned:
            summary['dqbuf_to_successful_qbuf'] = distribution(returned)
        state = Path(str(path) + '.sync')
        if state.exists():
            summary['fsync_snapshot'] = state.read_text().strip()
        result[str(path)] = summary
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('traces', nargs='+', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = json.dumps(analyze(args.traces), indent=2)
    if args.output:
        args.output.write_text(result + '\n')
    else:
        print(result)


if __name__ == '__main__':
    main()
