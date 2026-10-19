"""Exclusive unencoded-luma diagnostic; preserve and restore camera policy."""
import fcntl
import json
from pathlib import Path
import signal
import struct
import subprocess
import sys
import time
import numpy as np
from noise_analysis import analyze_patch
sys.path.insert(0,'/home/ubuntu/stereo-h265-rtsp')
import camera_platform as platform

OUT=Path('/home/ubuntu/hdr-tuning-20261012')/(sys.argv[1] if len(sys.argv)>1 else 'raw-noise10')
OUT.mkdir(exist_ok=False)
BOXES=((30,80,160,220),(500,470,660,620))

def finish(process):
    if process is not None and process.poll() is None:
        process.terminate()
        try: process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(timeout=5)

def analyze(directory):
    blob=(directory/'patches.bin').read_bytes()
    if blob[:8]!=b'SCNP001\0': raise RuntimeError('Patch format')
    size=16+sum((x1-x0)*(y1-y0)*2 for x0,y0,x1,y1 in BOXES)
    if (len(blob)-8)%size: raise RuntimeError('Truncated patch record')
    patches=[[[] for _ in BOXES] for _ in range(2)]
    stamps=[[],[]]
    for offset in range(8,len(blob),size):
        eye,sequence,stamp=struct.unpack_from('<IIq',blob,offset)
        if eye>1: raise RuntimeError('Eye index')
        stamps[eye].append((sequence,stamp))
        start=offset+16
        for index,(x0,y0,x1,y1) in enumerate(BOXES):
            count=(x1-x0)*(y1-y0)
            patches[eye][index].append(np.frombuffer(blob,'<u2',count,start).reshape(y1-y0,x1-x0))
            start+=count*2
    result=[]
    for eye in range(2):
        if len(stamps[eye])!=60: raise RuntimeError('Missing RAW frames')
        delta=np.diff(np.asarray(stamps[eye],dtype=np.int64),axis=0)
        if not np.all(delta[:,0]==1): raise RuntimeError('RAW frame sequence gap')
        for index,box in enumerate(BOXES):
            frames=np.stack(patches[eye][index])
            np.savez_compressed(directory/f'eye{eye}-patch{index}.npz',frames=frames)
            result.append(dict(eye=eye,box=box,**analyze_patch(frames)))
    return dict(frames_per_eye=[len(x) for x in stamps],
        receiver_fps=[(len(x)-1)*1e9/(x[-1][1]-x[0][1]) for x in stamps],patches=result)

with open('/run/sc132gs-camera.lock','a') as lock,open('/run/sc132gs-mode.lock','a') as legacy:
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    fcntl.flock(legacy,fcntl.LOCK_EX|fcntl.LOCK_NB)
    before=platform.inspect()
    previous=platform.configuration_from_state(before)
    durable=platform.DURABLE.read_bytes(); runtime=platform.STATE.read_bytes()
    (OUT/'before-settings.yaml').write_bytes(durable)
    record=dict(before=before,records=[],restored=False)
    generator=capture=None
    try:
        source=Path('/home/ubuntu/hdr-tuning-20261012')/(sys.argv[2] if len(sys.argv)>2 else 'equal-target-detrended10')/'comparison.json'
        baseline=json.loads(source.read_text())
        covered=len(sys.argv)>3 and sys.argv[3]=='covered'
        if covered:
            # Execute this branch only after human confirmation that both
            # lenses are covered. No lamp or display substitute is used.
            templates={entry['mode']:entry for entry in baseline}
            baseline=[]
            for mode in ('linear','hdr'):
                for gain in (0,11,21):
                    tokens=dict(t.split('=',1) for t in templates[mode]['status'].split()[1:])
                    tokens['exposure_lines']='672' if mode=='linear' else '1492'
                    tokens['gain_index']=str(gain)
                    baseline.append(dict(mode=mode,label=f'{mode}-gain{gain}',
                        status='ok '+' '.join(k+'='+v for k,v in tokens.items())))
            record['purpose']='covered unencoded black calibration'
        for entry in baseline:
            mode=entry['mode']
            controls=dict(t.split('=',1) for t in entry['status'].split()[1:])
            fps=entry.get('requested_fps',30)
            config=dict(previous,mode=mode,binning=0,fps=fps,max_fps=fps,ae=0,
                        rows=int(controls['exposure_lines']),gain=int(controls['gain_index']))
            directory=OUT/entry.get('label',mode); directory.mkdir()
            platform.stop(); platform.configure_profile(config)
            for node in platform.nodes():
                exposure='hdr_total_nominal_rows' if mode=='hdr' else 'exposure'
                values=exposure+'='+str(config['rows'])+',analogue_gain='+str(config['gain'])
                if mode=='hdr': values+=',hdr_total_second_ratio=256,hdr_second_exposure_ticks='+controls['hdr_second_ticks']
                platform.run(['v4l2-ctl','-d',node,'--set-ctrl='+values])
            platform.run(['/usr/local/sbin/prepare-sc132gs-sync-gpios'])
            with (directory/'fsync.log').open('w') as log:
                generator=subprocess.Popen(['/usr/local/bin/sc132gs-fsync-generator','auto','18','19',str(fps),'100','active-low'],stdout=log,stderr=subprocess.STDOUT)
            deadline=time.monotonic()+5
            while 'FSYNC generator armed' not in (directory/'fsync.log').read_text():
                if generator.poll() is not None or time.monotonic()>deadline: raise RuntimeError('FSYNC arm')
                time.sleep(.05)
            generator.send_signal(signal.SIGUSR1)
            devices=[platform.run(['/usr/local/sbin/sc132gs-discover',eye]) for eye in ('cam0','cam1')]
            with (directory/'capture.log').open('w') as log:
                capture=subprocess.Popen(['/home/ubuntu/hdr-tuning-20261012/build/raw-noise-capture',*devices,str(directory)],stdout=log,stderr=subprocess.STDOUT)
            if capture.wait(timeout=15): raise RuntimeError('RAW capture failed: '+(directory/'capture.log').read_text())
            finish(generator); generator=None; capture=None
            result=dict(mode=mode,configuration=config,raw=analyze(directory))
            if covered:
                result['black']=[]
                for eye in range(2):
                    pixels=np.fromfile(directory/f'eye{eye}-first-luma10.bin',dtype='<u2').reshape(1280,1088)
                    p99=float(np.percentile(pixels,99))
                    result['black'].append(dict(median=float(np.median(pixels)),
                        mean=float(pixels.mean()),p1=float(np.percentile(pixels,1)),p99=p99))
                    if p99>=200: raise RuntimeError('Covered check failed; both lenses must be opaque-covered')
            record['records'].append(result)
            (OUT/'comparison.json').write_text(json.dumps(record,indent=2))
            print(json.dumps(result),flush=True)
    finally:
        finish(capture); finish(generator)
        platform.stop(); platform.configure_profile(previous); platform.start(previous)
        platform.apply_exposure(previous); platform.verify(previous,True)
        if platform.DURABLE.read_bytes()!=durable or platform.STATE.read_bytes()!=runtime:
            raise RuntimeError('Saved configuration changed during RAW test')
        record['restored']=True; record['after']=platform.inspect()
        (OUT/'comparison.json').write_text(json.dumps(record,indent=2))
        print('Original camera policy restored; decoded RTSP verified',flush=True)
