#!/usr/bin/env python3
"""Characterize pulses/SOF/DMA without synthesizing frame timestamps."""
import argparse
import json
from pathlib import Path
import statistics
import bisect


parser = argparse.ArgumentParser()
parser.add_argument('input', type=Path)
args = parser.parse_args()
control=dict(t.split('=',1) for t in (args.input/'control.txt').read_text().split())
trigger_hz=int(control.get('trigger_hz',60))
frame_step=int(control.get('frame_step',2))
PERIOD_NS=round(1e9/trigger_hz)
events = [list(map(int, l.split())) for l in (args.input / 'events.txt').read_text().splitlines() if l and not l.startswith('#')]
sessions = sorted({e[1] for e in events})
if len(sessions)>1:
    events = [e for e in events if e[1]==sessions[-1]]
    sessions = sessions[-1:]
report = {'sessions': sessions, 'counts': {}, 'eyes': {}, 'passed': False}
for kind in range(1, 7): report['counts'][str(kind)] = sum(e[2] == kind for e in events)
if len(sessions) == 1:
    pulse = {e[5]: e for e in events if e[2] == 1}
    pv=sorted(pulse.values(),key=lambda e:e[4])
    pulse_times=[e[4] for e in pv]
    report['pulse_fps']=(len(pv)-1)*1e9/(pv[-1][4]-pv[0][4]) if len(pv)>1 else 0
    all_sof=[e for e in events if e[2]==2]
    training=[]
    first_sof=min((e[4] for e in all_sof),default=0)
    for e in all_sof:
        if not first_sof+2_000_000_000<=e[4]<=first_sof+12_000_000_000: continue
        index=bisect.bisect_right(pulse_times,e[4])-1
        if index>=0: training.append((e[4]-pv[index][4])%PERIOD_NS)
    # Estimate a narrow latency interval from the first ten steady seconds.
    # Circular phase is only used to find the interval. Association below
    # searches actual recorded pulses; it never rounds or rewrites timestamps.
    training.sort()
    if training:
        extended=training+[v+PERIOD_NS for v in training]
        n=len(training)
        at=min(range(n),key=lambda i:extended[i+n-1]-extended[i])
        minimum=max(0,extended[at]-500_000)
        maximum=extended[at+n-1]+500_000
    else: minimum=maximum=0
    report['candidate_window_us']=[minimum/1000,maximum/1000]
    mapping=[e for e in events if e[2]==8]
    report['hardware_clock_mapping']=bool(mapping) and all(e[7]==19200000 and 0<=e[4]-e[5]<1_000_000_000 for e in mapping)
    hw={ (e[3],e[8]):e for e in events if e[2]==7 }
    report['startup_invalid_buffers']=sum(e[2]==3 and e[9]==13 for e in events)
    dma=[e for e in events if e[2]==3 and e[9]!=13]
    bad_hw=0
    for e in dma:
        h=hw.get((e[3],e[8]))
        if not h: bad_hw+=1; continue
        frame=e[6]; current=h[5]; previous=h[6]; eof=h[7]
        valid=frame and current and eof and frame<=eof and (frame==current if eof>=current else frame==previous and previous<current)
        if not valid: bad_hw+=1
    report['hardware_buffer_identity_errors']=bad_hw
    delays = []
    identifiers = []
    for eye in (0, 1):
        sof = [e for e in events if e[2] == 2 and e[3] == eye]
        done = [e for e in events if e[2] == 3 and e[3] == eye]
        # Keep startup separate from the steady profile.
        if sof: sof = [e for e in sof if e[4] >= sof[0][4] + 2_000_000_000]
        eligible=[]
        ids=[]
        delay=[]
        ambiguous=0
        for e in sof:
            lo=bisect.bisect_left(pulse_times,e[4]-maximum)
            hi=bisect.bisect_right(pulse_times,e[4]-minimum)
            if hi-lo!=1: ambiguous+=1; continue
            index=lo
            eligible.append(e)
            ids.append(pv[index][5])
            delay.append((e[4]-pv[index][4])/1000)
        sof=eligible
        fps = (len(sof)-1)*1e9/(sof[-1][4]-sof[0][4]) if len(sof)>1 else 0
        report['eyes'][str(eye)] = dict(sof=len(sof), done=len(done), fps=fps,
            min_delay_us=min(delay,default=0), max_delay_us=max(delay,default=0),
            median_delay_us=statistics.median(delay) if delay else 0,
            unmatched_or_ambiguous=ambiguous,
            trigger_gaps=sum(b!=a+frame_step for a,b in zip(ids,ids[1:])),
            hw_nonzero=all(e[6]>0 for e in sof),
            hw_monotonic=all(a[6]<b[6] for a,b in zip(sof,sof[1:])),
            trigger_monotonic=all(a<b for a,b in zip(ids,ids[1:])))
        delays.extend(delay); identifiers.append(set(ids))
    shared = identifiers[0] & identifiers[1]
    union = identifiers[0] | identifiers[1]
    report['shared_triggers'] = len(shared)
    report['shared_fraction'] = len(shared)/len(union) if union else 0
    report['passed'] = not any(e[2]==4 for e in events) and bool(delays) and report['hardware_clock_mapping'] and bad_hw==0 and trigger_hz*.99<=report['pulse_fps']<=trigger_hz*1.01 and all(
        v['sof'] >= 100 and 29.7 <= v['fps'] <= 30.3 and
        v['hw_nonzero'] and v['hw_monotonic'] and v['trigger_monotonic'] and
        v['unmatched_or_ambiguous']==0 and v['trigger_gaps']==0
        for v in report['eyes'].values()) and report['shared_fraction'] > 0.98 and max(delays)-min(delays)<4000
    if report['passed']:
        report['sof_min_us'] = int(minimum/1000)
        report['sof_max_us'] = int(maximum/1000)+1
(args.input / 'analysis.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report, indent=2))
