#!/usr/bin/env python3
"""Measure R-Y-B with fixed Linear integration; never changes timestamp policy."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import signal
import statistics
import subprocess
import time

ROOT = Path(__file__).resolve().parent
CONTROL = Path('/sys/bus/platform/devices/acb3000.camss/fsync_control')
SETTINGS = Path('/var/lib/sc132gs-camera/settings.yaml')


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def stats(values):
    ordered = sorted(values)
    return dict(count=len(values), mean_ns=statistics.fmean(values),
                stddev_ns=statistics.pstdev(values), min_ns=ordered[0],
                median_ns=statistics.median(values),
                p95_ns=ordered[int((len(ordered)-1)*.95)], max_ns=ordered[-1])


def analyze(out):
    meta = json.loads((out/'measurement.json').read_text())
    trace = out.parent/(meta['run_name']+'-events')
    collection = json.loads((trace/'collection.json').read_text())
    assert collection['lost'] == 0
    assert collection['boot_id'] == collection['boot_id_final'] == meta['boot_id']
    assert all(all(v['rows'] == meta['rows'] for v in sample['controls'])
               for sample in meta['samples']) and len(meta['samples']) >= 10
    final = dict(t.split('=', 1) for t in (trace/'control-final.txt').read_text().split())
    assert final['error'] == final['skipped'] == '0'
    pulses, done = {}, [{}, {}]
    for line in (trace/'events.txt').read_text().splitlines():
        if line.startswith('#'): continue
        e = list(map(int, line.split()))
        if e[2] == 1: pulses[e[5]] = e
        if e[2] == 3 and e[3] in (0, 1) and e[9] == 0:
            assert e[5] not in done[e[3]]
            done[e[3]][e[5]] = e
        assert e[2] != 4, 'fatal synchronization error'
    ids = sorted(set(pulses) & set(done[0]) & set(done[1]))
    # Discard initial integration/control settling and the capture tail.
    ids = [i for i in ids if meta['start_ns']+2_000_000_000 <= pulses[i][6]
           < meta['end_ns']-1_000_000_000]
    assert len(ids) >= (meta['seconds']-5)*29.7
    assert all(b == a+1 for a, b in zip(ids, ids[1:]))
    exposure_ns = meta['rows']*1_000_000_000/meta['nominal_rows_per_second']
    delays = [[done[eye][i][4]-pulses[i][6] for i in ids] for eye in (0, 1)]
    first = [min(done[eye][i][4] for eye in (0, 1))-pulses[i][6] for i in ids]
    assert all(v > exposure_ns for v in first)
    result = dict(passed=True, matched_triggers=len(ids), first_trigger=ids[0],
                  last_trigger=ids[-1], rows=meta['rows'],
                  nominal_rows_per_second=meta['nominal_rows_per_second'],
                  nominal_B_ns=exposure_ns, formula='C = R - Y - B',
                  Y='raw actual GPIO-after host monotonic reference; not corrected DQBUF',
                  R='VFE DMA-done ISR host time; includes interrupt latency',
                  selection='first valid DMA-done of both eyes for each verified trigger',
                  first_R_minus_Y=stats(first),
                  first_C=stats([v-exposure_ns for v in first]),
                  per_eye_R_minus_Y=[stats(v) for v in delays],
                  per_eye_C=[stats([t-exposure_ns for t in v]) for v in delays],
                  trace_lost=0, physically_calibrated_exposure_start=False,
                  output_offset_unchanged=True,
                  limitations=['C combines trigger-to-exposure and readout/transport/IRQ latency',
                               'R-B equals exposure start plus post-exposure latency',
                               'B is register/row-rate nominal duration, not optical measurement'])
    (out/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('name')
    parser.add_argument('--seconds', type=int, default=125)
    parser.add_argument('--analyze-only', action='store_true')
    args = parser.parse_args()
    if args.analyze_only:
        analyze(Path(args.name))
        return
    assert args.name.replace('-', '').isalnum() and args.seconds >= 30
    out = ROOT/args.name
    out.mkdir(exist_ok=False)
    settings = SETTINGS.read_bytes()
    meta = dict(run_name=args.name, seconds=args.seconds, rows=1377,
                nominal_rows_per_second=84000,
                wall_start=datetime.now().astimezone().isoformat(),
                boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                settings_sha256=hashlib.sha256(settings).hexdigest(),
                before_control=CONTROL.read_text(),
                before_ae=run('sc132gs-ctl', 'status'), samples=[])
    (out/'settings-before.yaml').write_bytes(settings)
    child = None
    try:
        subprocess.run(['systemctl', 'stop', 'sc132gs-camera-restore.service',
                        'sc132gs-camera-rtsp.service'], check=True)
        nodes = []
        for client in ('18-0032', '16-0030'):
            found = list(Path('/sys/bus/i2c/devices', client, 'video4linux').glob('v4l-subdev*'))
            assert len(found) == 1
            node = '/dev/'+found[0].name
            subprocess.run(['v4l2-ctl', '-d', node, '--set-ctrl=exposure=1377'], check=True)
            nodes.append(node)
        meta['start_ns'] = time.monotonic_ns()
        child = subprocess.Popen(['bash', str(ROOT/'run_raw_probe.sh'), args.name, str(args.seconds)],
                                 start_new_session=True)
        while child.poll() is None:
            controls = []
            for node in nodes:
                text = run('v4l2-ctl', '-d', node, '--get-ctrl=exposure')
                controls.append(dict(node=node, rows=int(text.rsplit(':', 1)[1])))
            meta['samples'].append(dict(ns=time.monotonic_ns(), controls=controls))
            assert all(v['rows'] == 1377 for v in controls)
            time.sleep(5)
        assert child.returncode == 0
        meta['end_ns'] = time.monotonic_ns()
        assert SETTINGS.read_bytes() == settings, 'durable settings changed'
        analyze_ready = True
    finally:
        if child and child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
            child.wait(timeout=10)
        # The normal capture exit has STREAMOFFed both eyes before restoration.
        subprocess.run(['systemctl', 'restart', 'sc132gs-camera-restore.service'], check=True)
        meta['after_control'] = CONTROL.read_text()
        meta['after_ae'] = run('sc132gs-ctl', 'status')
        meta['settings_restored_identical'] = SETTINGS.read_bytes() == settings
        (out/'measurement.json').write_text(json.dumps(meta, indent=2)+'\n')
    assert analyze_ready and meta['settings_restored_identical']
    analyze(out)


if __name__ == '__main__':
    main()
