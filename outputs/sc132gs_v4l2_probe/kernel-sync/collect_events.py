#!/usr/bin/env python3
"""Persist ABI-v1 bounded kernel trace; fail if polling loses events."""
import argparse
import json
from pathlib import Path
import time
import signal

parser = argparse.ArgumentParser()
parser.add_argument('output', type=Path)
parser.add_argument('--seconds', type=float, default=90)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=False)
last = 0
lost = 0
control = Path('/sys/bus/platform/devices/acb3000.camss/fsync_control')
session = int(dict(token.split('=',1) for token in control.read_text().split())['session'])
provenance = {
    'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
    'module_srcversion': Path('/sys/module/qcom_camss/srcversion').read_text().strip(),
}
end = time.monotonic() + args.seconds
stopping=False
def stop(signum,frame):
    global stopping
    stopping=True
signal.signal(signal.SIGTERM,stop)
signal.signal(signal.SIGINT,stop)
try:
    with (args.output / 'events.txt').open('w') as stream:
        while time.monotonic() < end and not stopping:
            lines = Path('/sys/kernel/debug/sc132gs_sync/events').read_text().splitlines()
            for line in lines:
                if line.startswith('#'): continue
                serial = int(line.split()[0])
                if int(line.split()[1]) != session: continue
                if serial <= last: continue
                if last and serial != last + 1: lost += serial - last - 1
                stream.write(line + '\n')
                last = serial
            stream.flush()
            time.sleep(1)
    (args.output / 'collection.json').write_text(json.dumps({'session':session, 'last_serial': last, 'lost': lost, **provenance}, indent=2))
finally:
    control = Path('/sys/bus/platform/devices/acb3000.camss/fsync_control')
    if control.exists(): (args.output / 'control.txt').write_text(control.read_text())
if lost: raise SystemExit('Event trace lost records')
