#!/usr/bin/env python3
"""Bounded restoration check: one session, no error/skip, consumer affinity."""
import argparse,json,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('output',type=Path);p.add_argument('--seconds',type=float,default=605)
a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
control=Path('/sys/bus/platform/devices/acb3000.camss/fsync_control')
def state():return dict(t.split('=',1) for t in control.read_text().split())
initial=state();session=initial['session'];boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
start=time.monotonic();last=start;first_id=int(initial['pulses']);last_id=first_id;fault=None;samples=[]
try:
    while time.monotonic()-start<a.seconds:
        s=state();now=time.monotonic();s['elapsed_s']=now-start;samples.append(s)
        if any(s.get(k)!=initial.get(k) for k in ('abi','source','timestamp_offset_ns')):
            raise RuntimeError('timestamp publication contract changed')
        if s['session']!=session or s['running']!='1' or int(s['error']) or int(s['skipped']):
            raise RuntimeError('session stopped/changed or sync error/deadline miss')
        if s.get('locked_mask')!='3' or s.get('startup_dropped')!=initial.get('startup_dropped'):
            raise RuntimeError('qualification lost or new startup discard after lock')
        if s['cpu']==s.get('worker_cpu'):
            raise RuntimeError('worker and producer share a CPU')
        if now-last>0.9 and int(s['pulses'])<=last_id:
            raise RuntimeError('producer not advancing')
        last=now;last_id=int(s['pulses'])
        time.sleep(1)
    if Path('/proc/sys/kernel/random/boot_id').read_text().strip()!=boot:
        raise RuntimeError('boot changed')
    server='/home/ubuntu/stereo-h265-rtsp/build-main10/stereo-h265-rtsp'
    final=state()
    if final['session']!=session or final['running']!='1' or int(final['error']) or int(final['skipped']):
        raise RuntimeError('final synchronization state invalid')
    last_id=int(final['pulses'])
    pids=[]
    for v in Path('/proc').iterdir():
        if not v.name.isdecimal():continue
        try:command=(v/'cmdline').read_bytes().split(b'\0')[0].decode(errors='replace')
        except OSError:continue
        if command==server:pids.append(v)
    if len(pids)!=1:raise RuntimeError('one server owner required')
    affinity=[]
    for task in (pids[0]/'task').iterdir():
        try:status=(task/'status').read_text()
        except FileNotFoundError:continue
        line=next(v for v in status.splitlines() if v.startswith('Cpus_allowed_list:'))
        cpus=set()
        for part in line.split(':',1)[1].strip().split(','):
            lo,_,hi=part.partition('-');cpus.update(range(int(lo),int(hi or lo)+1))
        if int(initial['cpu']) in cpus:raise RuntimeError('consumer can run on producer CPU')
        affinity.append({'tid':int(task.name),'allowed':sorted(cpus)})
    if not affinity:raise RuntimeError('no live server threads')
except Exception as e:fault=str(e);affinity=[]
elapsed=time.monotonic()-start
result={'passed':fault is None,'error':fault,'session':int(session),'boot_id':boot,
        'abi':initial['abi'],'source':initial['source'],
        'timestamp_offset_ns':int(initial.get('timestamp_offset_ns','0')),
        'elapsed_s':elapsed,'pulse_fps':(last_id-first_id)/elapsed,'samples':len(samples),
        'producer_cpu':int(initial['cpu']),'worker_cpu':int(initial.get('worker_cpu',-1)),
        'consumer_affinity':affinity}
(a.output/'samples.json').write_text(json.dumps(samples,indent=2)+'\n')
(a.output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2));raise SystemExit(0 if result['passed'] else 1)
