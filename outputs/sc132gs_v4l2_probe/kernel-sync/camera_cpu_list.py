#!/usr/bin/env python3
"""Keep camera consumers off the running producer CPU; board-side only."""
from pathlib import Path
state=dict(t.split('=',1) for t in Path('/sys/bus/platform/devices/acb3000.camss/fsync_control').read_text().split())
producer=int(state['cpu'])
online=set()
for part in Path('/sys/devices/system/cpu/online').read_text().strip().split(','):
    lo,_,hi=part.partition('-')
    online.update(range(int(lo),int(hi or lo)+1))
online.discard(producer)
if not online:raise SystemExit('No consumer CPU separate from FSYNC producer')
print(','.join(str(c) for c in sorted(online)))
