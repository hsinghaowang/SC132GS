#!/usr/bin/env python3
"""Read-only resource snapshot of this test's known processes; never opens camera/IMU devices."""
import argparse
import json
from pathlib import Path
import subprocess
import time

ROOT = Path('/home/ubuntu/sc132gs-stability-20261015/revision-02')


def process(pid):
    directory = Path('/proc') / str(pid)
    try:
        status = dict(line.split(':', 1) for line in (directory / 'status').read_text().splitlines() if ':' in line)
        stat = (directory / 'stat').read_text()
        # Fields after the closing comm parenthesis start with field 3 (state).
        start_ticks = int(stat[stat.rfind(')') + 2:].split()[19])
        return dict(pid=pid, start_ticks=start_ticks, name=status['Name'].strip(),
            rss_kib=int(status.get('VmRSS', '0 kB').split()[0]),
            peak_rss_kib=int(status.get('VmHWM', '0 kB').split()[0]),
            anonymous_rss_kib=int(status.get('RssAnon', '0 kB').split()[0]),
            threads=int(status['Threads']), fd_count=len(list((directory / 'fd').iterdir())))
    except (FileNotFoundError, ProcessLookupError):
        return None


def tree(root):
    waiting, visited, values = [root], set(), []
    while waiting:
        pid = waiting.pop()
        if pid in visited:
            continue
        visited.add(pid)
        value = process(pid)
        if value is None:
            continue
        values.append(value)
        try:
            children = Path(f'/proc/{pid}/task/{pid}/children').read_text().split()
            waiting.extend(map(int, children))
        except (FileNotFoundError, ProcessLookupError):
            pass
    return dict(processes=values, total_rss_kib=sum(value['rss_kib'] for value in values),
                total_fds=sum(value['fd_count'] for value in values), total_threads=sum(value['threads'] for value in values))


def take_snapshot(output):
    progress = json.loads((ROOT / 'long-run/progress.json').read_text())
    state = dict(line.split('=', 1) for line in subprocess.check_output(['systemctl', 'show',
        'sc132gs-camera-rtsp.service', '--property=MainPID,ActiveState'], text=True, timeout=10).splitlines())
    monitor = dict(line.split('=', 1) for line in subprocess.check_output(['systemctl', 'show',
        'sc132gs-stability-long-20261015.service', '--property=MainPID,ActiveState'], text=True, timeout=10).splitlines())
    if state['ActiveState'] != 'active' or int(state['MainPID']) <= 0:
        raise RuntimeError('expected live RTSP owner')
    sample = dict(observed_monotonic_ns=time.monotonic_ns(),
        boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        elapsed_s=progress['elapsed_s'], camera=tree(int(state['MainPID'])),
        monitor=process(int(monitor['MainPID'])) if int(monitor['MainPID']) > 0 else None,
        imu=process(progress['imu_pid']))
    with output.open('a') as stream:
        stream.write(json.dumps(sample) + '\n')
    print(json.dumps(sample, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'long-run/resource-samples.jsonl')
    parser.add_argument('--interval', type=float, default=0, help='Repeat interval; zero takes one snapshot.')
    parser.add_argument('--maximum-seconds', type=float, default=5400)
    args = parser.parse_args()
    if args.interval < 0 or args.maximum_seconds <= 0:
        parser.error('invalid bounded observation duration')
    deadline = time.monotonic() + args.maximum_seconds
    while True:
        if args.interval:
            state = subprocess.run(['systemctl', 'is-active', 'sc132gs-stability-long-20261015.service'],
                                   capture_output=True, text=True, timeout=10)
            if state.stdout.strip() != 'active':
                break
        take_snapshot(args.output)
        if not args.interval or time.monotonic() >= deadline:
            break
        time.sleep(min(args.interval, max(0, deadline - time.monotonic())))


if __name__ == '__main__':
    main()
