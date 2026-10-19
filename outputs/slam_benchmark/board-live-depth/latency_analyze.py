"""Join decoded source watermarks to actual board frames using high-resolution PC time."""
from pathlib import Path
import json,sys
import numpy as np
p=Path(__file__).resolve().parent/sys.argv[1]
c=json.loads((p/'client.json').read_text())
assert c['pc_clock_resolution_s']<=1e-6,'Coarse PC clock cannot support precise latency'
before,after=c['clock_before'],c['clock_after']
assert before['rtt_ns']>0 and after['rtt_ns']>0
board=np.genfromtxt(p/'depth.csv',delimiter=',',names=True)
stamps=set(map(int,board['stamp_ns']))
rows=c['depth']['rows'];valid=[r for r in rows if r['marker_ok'] and r['stamp_ns'] in stamps]
assert len(valid)==len(rows),'Corrupted/unmatched watermark'
assert len(set(r['stamp_ns'] for r in valid))==len(valid),'Repeated source frame'
assert all(b['stamp_ns']>a['stamp_ns'] for a,b in zip(valid,valid[1:]))
latency=[]
for row in valid:
    t=(row['pc_ns']-before['pc_mid_ns'])/(after['pc_mid_ns']-before['pc_mid_ns'])
    offset=before['offset_ns']+t*(after['offset_ns']-before['offset_ns'])
    latency.append((row['pc_ns']+offset-row['stamp_ns'])/1e6)
assert min(latency)>0
report=dict(samples=len(valid),pc_clock=c['pc_clock'],clock_offset_drift_ms=(after['offset_ns']-before['offset_ns'])/1e6,clock_min_rtt_half_ms=max(before['rtt_ns'],after['rtt_ns'])/2e6,
            latency_ms=dict(zip(['p50','p95','p99'],map(float,np.percentile(latency,[50,95,99])))),
            start='driver exposure_start_estimate',end='PC decoder-ready',watermarks_exactly_joined=True,unique_frames=True,
            source_timestamp_fps=(len(valid)-1)*1e9/(valid[-1]['stamp_ns']-valid[0]['stamp_ns']),
            pc_decode_fps=(len(valid)-1)*1e9/(valid[-1]['pc_ns']-valid[0]['pc_ns']))
(p/'latency-summary.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
