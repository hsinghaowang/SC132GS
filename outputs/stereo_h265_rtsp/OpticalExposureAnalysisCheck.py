#!/usr/bin/env python3
"""Synthetic model checks, separate from physical exposure synchronization proof."""
import contextlib
import io
import json
from pathlib import Path
import struct
import tempfile
import numpy as np
from analyze_optical_exposure import analyze

def fixture(root,case):
    exposure=2000
    events=[dict(before_ns=int(t*1e6),after_ns=int(t*1e6)+1000,value=value,stage=stage)
        for t,value,stage in ((0,0,'calibration_dark'),(1200,511,'calibration_light'),(2400,0,'calibration_dark2'))]
    for i in range(24):
        events.append(dict(before_ns=int((3591+i*100)*1e6),after_ns=int((3591+i*100)*1e6)+1000,
            value=511 if i%2==0 else 0,stage='transition'))
    events.append(dict(before_ns=6_100_000_000,after_ns=6_100_001_000,value=0,stage='finished'))
    (root/'transaction.json').write_text(json.dumps(dict(nominal_exposure_us=exposure,
        test=dict(fps=60 if case=='cadence_mismatch' else 30))))
    (root/'led-events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
    def fraction(start):
        end=start+2
        total=0
        for index,event in enumerate(events):
            if not event['value']: continue
            a=event['before_ns']/1e6
            b=events[index+1]['before_ns']/1e6
            total+=max(0,min(end,b)-max(start,a))
        return total/2
    count=25
    dtype=np.dtype([('eye','<u4'),('sequence','<u4'),('flags','<u4'),('count','<u4'),
        ('receiver_ns','<i8'),('dequeue_ns','<i8'),('tiles','<u2',(count,)),('saturated','u1',(count,))])
    records=np.zeros(2*183,dtype=dtype)
    for sequence in range(183):
        deque_ms=20+sequence*1000/30
        for eye in (0,1):
            row=records[sequence*2+eye]
            row['eye']=eye; row['sequence']=sequence; row['count']=count
            row['dequeue_ns']=round(deque_ms*1e6)
            row['receiver_ns']=round(deque_ms*1e6)-2_000_000+eye*7_000_000
            offset=(3 if case=='missing_overlap' else .5) if eye else 0
            f=fraction(deque_ms-30+offset)
            if case=='edge_bias' and eye and 0<f<1 and sequence>=108:
                recent=[e for e in events if e['before_ns']<row['dequeue_ns']-25_000_000]
                if recent and recent[-1]['value']==0: f=fraction(deque_ms-30)
            amplitude=5 if case=='weak' else (400 if eye==0 else 600)
            row['tiles']=round(100+amplitude*f)
            if case=='saturated' and f>.9: row['saturated']=64
            if case=='halo':
                row['tiles'][12]=round(100+923*f)
                if f>.99: row['saturated'][12]=64
    (root/'frames.bin').write_bytes(b'SCOP001\0'+struct.pack('<III',40,40,8)+records.tobytes())

def main():
    for case in ('valid','halo','saturated','weak','missing_overlap','edge_bias','cadence_mismatch'):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); fixture(root,case)
            with contextlib.redirect_stdout(io.StringIO()): result=analyze(root)
            if case in ('valid','halo'):
                assert result['status']=='conditional_estimate',result['failed_checks']
                assert abs(result['estimate']['median_start_skew_us']-500)<10,result['estimate']
                assert result['valid_joint_events']>=20,result['valid_joint_events']
                assert not result['exposure_sync_verified']
                assert result['calibrated_accuracy_us'] is None
            else:
                assert result['status']=='inconclusive',(case,result['failed_checks'])
                assert result['estimate'] is None
            print(case+': PASS')
if __name__=='__main__': main()
