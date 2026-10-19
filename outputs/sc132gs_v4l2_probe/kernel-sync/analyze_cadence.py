#!/usr/bin/env python3
"""Report actual host GPIO brackets, never claim electrical edge precision."""
import argparse,json,statistics
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('events',type=Path);a=p.parse_args()
rows=[list(map(int,l.split())) for l in (a.events/'events.txt').read_text().splitlines() if l and not l.startswith('#')]
pulses=sorted((r for r in rows if r[2]==1),key=lambda r:r[5]);deassert={r[5]:r for r in rows if r[2]==9}
def stats(v):return dict(min=min(v),median=statistics.median(v),max=max(v)) if v else {}
first=pulses[0]
control=dict(t.split('=',1) for t in (a.events/'control.txt').read_text().split())
hz=int(control.get('trigger_hz',60));period_ns=round(1e9/hz)
phase=[r[4]-first[4]-(r[5]-first[5])*period_ns for r in pulses]
result={'trigger_hz':hz,'period_ns':period_ns,'pulse_count':len(pulses),'pulse_fps':(len(pulses)-1)*1e9/(pulses[-1][4]-first[4]),
        'trigger_id_gaps':sum(b[5]!=a[5]+1 for a,b in zip(pulses,pulses[1:])),
        'actual_assert_interval_ns':stats([b[4]-a[4] for a,b in zip(pulses,pulses[1:])]),
        'host_assert_bracket_width_ns':stats([r[6]-r[4] for r in pulses]),
        'host_low_duration_lower_bound_ns':stats([deassert[r[5]][4]-r[6] for r in pulses if r[5] in deassert]),
        'relative_phase_residual_ns':stats(phase),'end_to_start_phase_residual_ns':phase[-1],
        'source':'host GPIO operation brackets; electrical edge and exposure unmeasured'}
(a.events/'cadence.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
