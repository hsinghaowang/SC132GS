#!/usr/bin/env python3
"""Drain trace tail after both capture and the bounded collector have exited."""
import json
from pathlib import Path
import sys
root=Path(sys.argv[1])
record=json.loads((root/'collection.json').read_text())
last=record['last_serial']
with (root/'events.txt').open('a') as output:
    for line in Path('/sys/kernel/debug/sc132gs_sync/events').read_text().splitlines():
        if line.startswith('#'): continue
        values=line.split()
        if int(values[0])>last and int(values[1])==record['session']:
            if last and int(values[0])!=last+1: record['lost']+=int(values[0])-last-1
            output.write(line+'\n')
            last=int(values[0])
record['last_serial']=last
boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
if 'boot_id' in record and record['boot_id'] != boot_id:
    raise SystemExit('Boot changed during acquisition')
record['boot_id_final']=boot_id
(root/'control-final.txt').write_text(Path('/sys/bus/platform/devices/acb3000.camss/fsync_control').read_text())
(root/'collection.json').write_text(json.dumps(record,indent=2)+'\n')
if record['lost']: raise SystemExit('Trace has missing records')
