#!/usr/bin/env python3
"""Calibrate causal latency from known exposure settings, never nearest pulse."""
import argparse,bisect,json,statistics
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--name',default='exposure-boundaries');p.add_argument('--period-ns',type=int,default=33333333);p.add_argument('--step',type=int,default=1);a=p.parse_args();root=a.root
text=(root/(a.name+'-controls.txt')).read_text().splitlines()
changes=[(int(text[i]),int(text[i+1].split(':')[1])) for i in range(0,len(text),3)]
events=[list(map(int,l.split())) for l in (root/(a.name+'-events')/'events.txt').read_text().splitlines() if not l.startswith('#')]
pulses=sorted((r for r in events if r[2]==1),key=lambda r:r[4]);times=[r[4] for r in pulses]
sof=[r for r in events if r[2]==2 and r[4]>changes[0][0]+2_000_000_000]
def candidates(ns,lo,hi):return pulses[bisect.bisect_left(times,ns-hi):bisect.bisect_right(times,ns-lo)]
# The previously accepted 1330-row profile anchors the latency offset. Static
# setting intervals are verified by S_CTRL readback; allow two seconds to settle.
anchors=[]
for index,(start,rows) in enumerate(changes):
    end=changes[index+1][0] if index+1<len(changes) else 10**30
    if rows!=1330:continue
    for r in sof:
        if start+2_000_000_000<=r[4]<end-1_000_000_000:
            c=candidates(r[4],15684000,16705000)
            if len(c)!=1:raise SystemExit('1330-row causal anchor not unique')
            anchors.append(r[4]-c[0][4]-rows*1e9/84000)
offset=statistics.median(anchors)
profiles=[];all_delays=[]
for index,(start,rows) in enumerate(changes):
    end=changes[index+1][0] if index+1<len(changes) else 10**30
    expected=offset+rows*1e9/84000;delays=[]
    for r in sof:
        if start+2_000_000_000<=r[4]<end-1_000_000_000:
            c=candidates(r[4],expected-75000,expected+75000)
            if len(c)!=1:raise SystemExit(f'{rows}-row measured latency not unique')
            delays.append(r[4]-c[0][4])
    if len(delays)<500:raise SystemExit('insufficient stable exposure samples')
    rates={}
    for eye in (0,1):
        eye_sof=[r for r in sof if r[3]==eye and start+2_000_000_000<=r[4]<end-1_000_000_000]
        rates[str(eye)]=(len(eye_sof)-1)*1e9/(eye_sof[-1][4]-eye_sof[0][4])
    profiles.append({'rows':rows,'samples':len(delays),'eye_fps':rates,'min_ns':min(delays),'median_ns':statistics.median(delays),'max_ns':max(delays)})
    all_delays+=delays
minimum=max(0,min(all_delays)-100000);maximum=max(all_delays)+100000
minimum=minimum//1000*1000;maximum=(maximum+999)//1000*1000
ids=[[],[]];bad=0
for r in sof:
    c=candidates(r[4],minimum,maximum)
    if len(c)!=1:bad+=1;continue
    ids[r[3]].append(c[0][5])
step=a.step
gaps=[sum(right!=left+step for left,right in zip(v,v[1:])) for v in ids]
phase_mismatch=a.step==2 and bool(ids[0] and ids[1] and ((ids[0][0]^ids[1][0])&1))
collection=json.loads((root/(a.name+'-events')/'collection.json').read_text())
pulse_fps=(len(pulses)-1)*1e9/(pulses[-1][4]-pulses[0][4])
bad_hardware=sum(r[9]!=0 for r in events if r[2] in (7,8) and r[4]>changes[0][0]+2_000_000_000)
report={'passed':maximum-minimum<a.period_ns-100000 and maximum<a.period_ns-100000 and bad==0 and not any(gaps) and not phase_mismatch and collection['lost']==0 and bad_hardware==0 and 29.7<=pulse_fps<=30.3 and all(29.7<=fps<=30.3 for profile in profiles for fps in profile['eye_fps'].values()),
        'sof_min_us':minimum//1000,'sof_max_us':maximum//1000,'exposure_min_rows':8,'exposure_max_rows':1377,
        'maximum_window_ns':a.period_ns-100000,'window_ns':maximum-minimum,'unique_sof':len(sof)-bad,
        'unmatched_or_ambiguous':bad,'trigger_gaps':gaps,'phase_mismatch':phase_mismatch,
        'trigger_hz':round(1e9/a.period_ns),'frame_step':a.step,'offset_ns':offset,'pulse_fps':pulse_fps,'hardware_errors':bad_hardware,'profiles':profiles,'source':'1330-row measured causal anchor plus stable exposure control readback; actual recorded pulse search'}
(root/(a.name+'-characterization.json')).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
raise SystemExit(0 if report['passed'] else 1)
