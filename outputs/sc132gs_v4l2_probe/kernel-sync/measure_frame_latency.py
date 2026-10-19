#!/usr/bin/env python3
"""Read-only live latency measurement; never acquires video nodes or controls FSYNC."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time

CONTROL = Path('/sys/bus/platform/devices/acb3000.camss/fsync_control')


def state():
    return dict(token.split('=', 1) for token in CONTROL.read_text().split())


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def stats(values):
    ordered = sorted(values)
    return dict(count=len(values), mean_ns=statistics.fmean(values),
                median_ns=statistics.median(values), stddev_ns=statistics.pstdev(values),
                min_ns=ordered[0], p95_ns=ordered[int((len(values)-1)*.95)], max_ns=ordered[-1])


def analyze(root):
    meta = json.loads((root/'measurement.json').read_text())
    collection = json.loads((root/'trace/collection.json').read_text())
    assert collection['lost'] == 0
    assert collection['boot_id'] == collection['boot_id_final'] == meta['boot_id']
    assert collection['session'] == int(meta['initial']['session'])
    pulses, done = {}, [{}, {}]
    faults = []
    for line in (root/'trace/events.txt').read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        e = list(map(int, line.split()))
        if e[2] == 1 and meta['start_ns'] <= e[6] < meta['end_ns']:
            pulses[e[5]] = e
        if e[2] == 3 and e[3] in (0, 1) and e[9] == 0:
            assert e[5] not in done[e[3]], 'duplicate DMA identity'
            done[e[3]][e[5]] = e
        if e[2] == 4 and meta['start_ns'] <= e[4] < meta['end_ns']:
            faults.append(e)
    ids = sorted(set(pulses) & set(done[0]) & set(done[1]))
    assert len(ids) >= (meta['end_ns']-meta['start_ns'])/1e9*29.7-5
    assert not faults and all(b == a+1 for a, b in zip(ids, ids[1:]))
    assert all(len([i for i in done[eye] if ids[0] <= i <= ids[-1]]) == len(ids) for eye in (0, 1))
    delays, sof_delays, first, first_eye = [[], []], [[], []], [], [0, 0]
    windows = {}
    for trigger in ids:
        pulse = pulses[trigger]
        for eye in (0, 1):
            event = done[eye][trigger]
            assert event[1] == pulse[1] and event[4] >= event[7] >= pulse[6]
            delays[eye].append(event[4]-pulse[6])
            sof_delays[eye].append(event[7]-pulse[6])
        eye = 0 if done[0][trigger][4] <= done[1][trigger][4] else 1
        delay = done[eye][trigger][4]-pulse[6]
        first.append(delay)
        first_eye[eye] += 1
        index = int((pulse[6]-meta['start_ns'])//10_000_000_000)
        windows.setdefault(index, []).append(delay)
    result = dict(passed=True, matched_triggers=len(ids), first_trigger=ids[0], last_trigger=ids[-1],
                  elapsed_s=(meta['end_ns']-meta['start_ns'])/1e9,
                  reference='actual FSYNC pulse.after (current buffer timestamp before timeval truncation)',
                  frame_event='VFE DMA completion in kernel; not userspace DQBUF return time',
                  selection='first of the two valid DMA completions belonging to the same verified trigger',
                  first_frame=stats(first), per_eye_dma=[stats(v) for v in delays],
                  per_eye_sof=[stats(v) for v in sof_delays], first_eye_counts=first_eye,
                  ten_second_windows=[dict(index=i, **stats(v)) for i, v in sorted(windows.items())],
                  proposed_common_offset_ns=round(statistics.fmean(first)/2),
                  timestamp_modified=False, trace_lost=collection['lost'],
                  source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  limitations=['AE remains enabled; exposure readbacks are periodic, not per-frame metadata',
                               'DMA latency includes sensor output and receiver completion latency',
                               'not a measurement of exposure start or exposure midpoint'])
    (root/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('output', type=Path)
    p.add_argument('--seconds', type=float, default=120)
    p.add_argument('--analyze-only', action='store_true')
    a = p.parse_args()
    if a.analyze_only:
        analyze(a.output)
        return
    a.output.mkdir(parents=True, exist_ok=False)
    initial = state()
    assert initial['mode'] == '2' and initial['running'] == '1' and initial['error'] == '0'
    assert initial['locked_mask'] == '3' and initial['skipped'] == '0'
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    owner = command('systemctl', 'show', 'sc132gs-camera-rtsp.service', '-p', 'MainPID', '-p', 'ActiveState', '-p', 'NRestarts')
    meta = dict(start_ns=time.monotonic_ns(), initial=initial, boot_id=boot, service_before=owner,
                module_srcversion=Path('/sys/module/qcom_camss/srcversion').read_text().strip(),
                wall_start=datetime.now().astimezone().isoformat(), samples=[])
    here = Path(__file__).resolve().parent
    child = subprocess.Popen([sys.executable, str(here/'collect_events.py'), str(a.output/'trace'), '--seconds', str(a.seconds)])
    try:
        while child.poll() is None:
            current = state()
            assert current['session'] == initial['session'] and current['running'] == '1'
            assert current['error'] == '0' and current['skipped'] == '0' and current['locked_mask'] == '3'
            meta['samples'].append(dict(ns=time.monotonic_ns(), state=current, ae=command('sc132gs-ctl', 'status')))
            time.sleep(5)
        assert child.returncode == 0
        meta['end_ns'] = time.monotonic_ns()
        meta['final'] = state()
        meta['service_after'] = command('systemctl', 'show', 'sc132gs-camera-rtsp.service', '-p', 'MainPID', '-p', 'ActiveState', '-p', 'NRestarts')
        assert meta['service_after'] == owner
        subprocess.run([sys.executable, str(here/'finalize_events.py'), str(a.output/'trace')], check=True)
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=10)
        (a.output/'measurement.json').write_text(json.dumps(meta, indent=2)+'\n')
    analyze(a.output)


if __name__ == '__main__':
    main()
