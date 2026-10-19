#!/usr/bin/env python3
"""Verify original DQBUF values against the kernel's per-buffer trigger IDs."""
import argparse
import csv
import json
from pathlib import Path
parser=argparse.ArgumentParser()
parser.add_argument('raw',type=Path)
parser.add_argument('events',type=Path)
parser.add_argument('--minimum-seconds',type=float,default=600)
parser.add_argument('--swap-eyes',action='store_true')
args=parser.parse_args()
rows=[{k:int(v) for k,v in r.items()} for r in csv.DictReader((args.raw/'buffers.csv').open())]
if args.swap_eyes:
    for r in rows: r['eye']=1-r['eye']
events=[list(map(int,l.split())) for l in (args.events/'events.txt').read_text().splitlines() if not l.startswith('#')]
trigger={e[5]:e[6] for e in events if e[2]==1}
done={(e[3],e[8]):e for e in events if e[2]==3}
collection=json.loads((args.events/'collection.json').read_text())
control=dict(t.split('=',1) for t in (args.events/'control-final.txt').read_text().split())
offset=int(control.get('timestamp_offset_ns','0'))
source=control.get('source')
assert (offset==0 and source=='fsync_host_reference') or (offset>0 and (
    (source=='exposure_midpoint_estimate' and control['abi']=='3') or
    (source=='exposure_start_estimate' and control['abi']=='4')))
exit_path=args.raw.parent/(args.raw.name.removesuffix('-raw')+'-exit.txt')
provenance_ok=(exit_path.read_text().strip()=='0' and collection['lost']==0 and
    collection.get('boot_id')==collection.get('boot_id_final') and
    len({e[1] for e in events})==1 and not any(e[2]==4 for e in events) and
    control['mode']=='2' and control['trigger_hz']=='30' and control['frame_step']=='1' and
    int(control['session'])==collection['session'] and control['error']=='0' and control['skipped']=='0')
report={'eyes':{},'passed':False,'identity_errors':0,'provenance_ok':provenance_ok,
    'timestamp_offset_ns':offset,'source':source,
    'startup_invalid_buffers':sum(e[2]==3 and e[9]==13 for e in events)}
timestamps=[]
for eye in (0,1):
    frames=[r for r in rows if r['eye']==eye]
    if not frames: continue
    duration=(frames[-1]['timestamp_ns']-frames[0]['timestamp_ns'])/1e9
    rate=(len(frames)-1)/duration if duration>0 else 0
    gaps=sum(b['sequence']!=a['sequence']+1 for a,b in zip(frames,frames[1:]))
    monotonic=all(a['timestamp_ns']<b['timestamp_ns'] for a,b in zip(frames,frames[1:]))
    invalid=sum(not bool(f['flags'] & 0x2000) or bool(f['flags'] & 0x40) or f['bytes']!=1740800 for f in frames)
    for f in frames:
        e=done.get((eye,f['sequence']))
        stamp=trigger.get(e[5]) if e else None
        if stamp is None or (stamp+offset)//1000*1000!=f['timestamp_ns'] or e[9]:
            report['identity_errors']+=1
    report['eyes'][str(eye)]=dict(frames=len(frames),duration_s=duration,fps=rate,
        gaps=gaps,monotonic=monotonic,invalid=invalid)
    timestamps.append({f['timestamp_ns'] for f in frames})
if len(timestamps)==2:
    report['exact_pairs']=len(timestamps[0]&timestamps[1])
    report['unpaired']=[len(s)-report['exact_pairs'] for s in timestamps]
    report['maximum_pair_delta_ns']=0
    report['passed']=provenance_ok and report['identity_errors']==0 and report['exact_pairs']>=100 and all(
        r['duration_s']>=args.minimum_seconds and 29.7<=r['fps']<=30.3 and
        not r['gaps'] and r['monotonic'] and not r['invalid'] for r in report['eyes'].values())
    # Only startup/tail differences may be unpaired. Internal omissions have
    # different timestamp sets inside their overlapping acquisition interval.
    if timestamps[0] and timestamps[1]:
        lo=max(min(s) for s in timestamps); hi=min(max(s) for s in timestamps)
        middle=[{v for v in s if lo<=v<=hi} for s in timestamps]
        report['internal_unpaired']=len(middle[0]^middle[1])
        report['passed'] &= report['internal_unpaired']==0
(args.raw/'analysis.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
raise SystemExit(0 if report['passed'] else 1)
