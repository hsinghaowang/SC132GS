#!/usr/bin/env python3
"""Read-only bounded live trace and process check for the 200us deployment."""
import json
from pathlib import Path
import subprocess
import time
from audit_stability import Checks, trace

ROOT = Path('/home/ubuntu/sc132gs-envelope-200us-20261016')
OUT = ROOT / 'live-300s'
OUT.mkdir()
CONTROL = Path('/sys/bus/platform/devices/acb3000.camss/fsync_control')
EVENTS = Path('/sys/kernel/debug/sc132gs_sync/events')


def snapshot():
    control = dict(token.split('=', 1) for token in CONTROL.read_text().split())
    service = subprocess.check_output(['systemctl', 'show', 'sc132gs-camera-rtsp.service',
        '-p', 'MainPID', '-p', 'NRestarts', '-p', 'ActiveState'], text=True)
    return dict(elapsed_s=time.monotonic() - start, control=control,
                service=dict(line.split('=', 1) for line in service.splitlines()))


start = time.monotonic()
first = snapshot()
session = int(first['control']['session'])
provenance = dict(control=first['control'], boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                  module_srcversion=Path('/sys/module/qcom_camss/srcversion').read_text().strip())
(OUT / 'provenance.json').write_text(json.dumps(provenance, indent=2))
last = 0
lost = 0
samples = []
failures = []
with (OUT / 'events.txt').open('w') as stream:
    while True:
        for line in EVENTS.read_text().splitlines():
            if line.startswith('#') or not line.strip():
                continue
            fields = line.split()
            serial = int(fields[0])
            if int(fields[1]) != session or serial <= last:
                continue
            if last and serial != last + 1:
                lost += serial - last - 1
            stream.write(line + '\n')
            last = serial
        stream.flush()
        sample = snapshot()
        samples.append(sample)
        c = sample['control']
        if any(c.get(key) != value for key, value in dict(session=str(session), error='0',
                error_count='0', skipped='0', running='1', locked_mask='3').items()):
            failures.append('unhealthy_control')
        if sample['service'] != first['service'] or sample['service'].get('ActiveState') != 'active':
            failures.append('service_changed')
        if failures or sample['elapsed_s'] >= 300:
            break
        time.sleep(1)
(OUT / 'samples.json').write_text(json.dumps(samples, indent=2))
(OUT / 'control-final.txt').write_text(CONTROL.read_text())
checks = Checks()
replay = trace(OUT / 'events.txt', session, checks, envelope_ns=200000)
result = dict(passed=not failures and not checks.errors and not lost and samples[-1]['elapsed_s'] >= 300,
              duration_s=samples[-1]['elapsed_s'], failures=failures, lost_events=lost,
              errors=dict(checks.errors), examples=checks.examples, trace=replay,
              envelope_ns=200000, release_overrun_ns=25000,
              scope='Bounded host timing/SOF/DMA trace and stable service; no electrical timing or long-run acceptance.')
(OUT / 'result.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
raise SystemExit(0 if result['passed'] else 1)
