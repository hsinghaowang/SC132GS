"""Full RAW comparison with exclusive ownership and original-policy restoration."""
import fcntl
import hashlib
import json
from pathlib import Path
import signal
import subprocess
import sys
import time
import re
import numpy as np
from PIL import Image
sys.path.insert(0,'/home/ubuntu/stereo-h265-rtsp')
import camera_platform as platform

ROOT=Path('/home/ubuntu/hdr-tuning-20261012')
OUT=ROOT/(sys.argv[1] if len(sys.argv)>1 else 'haze-covered-20261012')
covered=len(sys.argv)<3 or sys.argv[2]=='covered'
OUT.mkdir(exist_ok=False)
COUNT=32
SIZE=1740800
timing=len(sys.argv)>3 and sys.argv[3]=='timing'
signal_comparison=len(sys.argv)>3 and sys.argv[3]=='signal'
flat=len(sys.argv)>3 and sys.argv[3]=='flat'
vendor=len(sys.argv)>3 and sys.argv[3]=='vendor'
wide=len(sys.argv)>3 and sys.argv[3]=='wide'
claims=len(sys.argv)>3 and sys.argv[3]=='claims'
free30=len(sys.argv)>3 and sys.argv[3]=='free30'
free_static=len(sys.argv)>3 and sys.argv[3]=='free-static'
CASES=(
    ('hdr-short15', 'hdr',15,1492,False,1,0),
    ('hdr-long15', 'hdr',15,4350,False,1,0),
    ('hdr-short30', 'hdr',30,1492,False,1,0),
    ('hdr-free-long', 'hdr',15,4350,True,1,0),
    ('hdr-long15-repeat', 'hdr',15,4350,False,1,0),
    ('linear30', 'linear',30,1377,False,1,0)) if not timing else (
    ('external-short', 'hdr',15,1492,False,1,0),
    ('free-short', 'hdr',15,1492,True,1,0),
    ('external-short-repeat', 'hdr',15,1492,False,1,0),
    ('long-second16', 'hdr',15,4350,False,16,0),
    ('long-second64', 'hdr',15,4350,False,64,0),
    ('long-second272', 'hdr',15,4350,False,272,0),
    ('external-long-vts9000', 'hdr',15,4350,False,1,9000),
    ('free-long-vts9000', 'hdr',15,4350,True,1,9000),
    ('external-long-vts9000-repeat', 'hdr',15,4350,False,1,9000))
CASES=[(*case,0,True) for case in CASES]
if signal_comparison:
    CASES=(
        ('long-hdrc-on','hdr',15,4350,False,1,0,0,True),
        ('long-hdrc-off','hdr',15,4350,False,1,0,0,False),
        ('long-hdrc-on-repeat','hdr',15,4350,False,1,0,0,True),
        ('medium3629-gain9','hdr',15,3629,False,1,0,9,True),
        ('medium2560-gain24','hdr',15,2560,False,1,0,24,True),
        ('short1492-gain49','hdr',15,1492,False,1,0,49,True))
if flat:
    CASES=(
        ('flat-linear30','linear',30,1377,False,1,0,0,True),
        ('flat-hdr-short15','hdr',15,1492,False,1,0,0,True),
        ('flat-hdr-medium2560','hdr',15,2560,False,1,0,0,True),
        ('flat-hdr-medium3629','hdr',15,3629,False,1,0,0,True),
        ('flat-hdr-long4350','hdr',15,4350,False,1,0,0,True),
        ('flat-hdr-long4350-repeat','hdr',15,4350,False,1,0,0,True),
        ('flat-linear30-repeat','linear',30,1377,False,1,0,0,True))
if wide:
    CASES=tuple((f'second{second}-{index}','hdr',15,4350,False,second,0,0,True)
                for index,second in enumerate((1,1024,4096,8192,16384,1)))
if claims:
    CASES=tuple((name,'hdr',15,4350,False,1,0,0,True) for name in
        ('claims-baseline','claims-blc-reenable','claims-short-gain1x',
         'claims-baseline-repeat'))
if free30:
    CASES=(
        ('hdr15-long-reference','hdr',15,4350,False,1,0,0,True),
        ('hdr30-external','hdr',30,1492,False,1,0,0,True),
        ('hdr30-free-no-fsync','hdr',30,1492,True,1,0,0,True),
        ('hdr30-external-repeat','hdr',30,1492,False,1,0,0,True),
        ('hdr15-long-reference-repeat','hdr',15,4350,False,1,0,0,True))
if free_static:
    CASES=(
        ('no-fsync-vendor-seed30','hdr',30,1492,True,746,0,0,True),
        ('no-fsync-vendor-short30','hdr',30,1492,True,1,0,0,True),
        ('no-fsync-vendor-safe30','hdr',30,1259,True,79,0,0,True),
        ('external-safe30','hdr',30,1259,False,79,0,0,True),
        ('no-fsync-vendor-long15','hdr',15,4350,True,1,9000,0,True),
        ('external-short30-repeat','hdr',30,1492,False,1,0,0,True))
if vendor:
    CASES=(
        ('external-long-baseline','hdr',15,4350,False,1,9000,0,True),
        ('vendor-reset-long','hdr',15,4350,True,1,9000,0,True),
        ('external-long-repeat','hdr',15,4350,False,1,9000,0,True),
        ('vendor-reset-short','hdr',15,1492,True,1,0,0,True),
        ('external-short-repeat','hdr',15,1492,False,1,0,0,True))
if vendor or free_static:
    table=(ROOT/'source/sc132gs_v4l2_probe/sc132gs-hdr-settings.h').read_text()
    VENDOR_REGS=[(int(a,16),int(v,16)) for a,v in re.findall(r'\{(0x[0-9a-f]+),\s*(0x[0-9a-f]+)\}',table)]
    if len(VENDOR_REGS)<100: raise RuntimeError('Incomplete vendor HDR table')

def finish(process):
    if process is not None and process.poll() is None:
        process.terminate()
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)

def registers():
    result=[]
    for bus,addr in ((18,'0x32'),(16,'0x30')):
        values={}
        for name,reg,count in (('mode',0x3220,1),('trigger',0x3222,1),('gate',0x3225,1),
                               ('hdrc_enable',0x5001,1),('trigger_reset',0x3226,2),
                               ('readout',0x3260,2),('vts',0x320e,2),('hts',0x320c,2),
                               ('total',0x3e00,3),('second',0x3e31,2),('gain',0x3e08,2),
                               ('hdrc_ratio',0x5400,1),('blc_auto',0x3902,1),
                               ('blc_auto_aux',0x391d,1),('gain_control',0x3e03,1),
                               ('short_gain',0x3e10,4),('vendor_325x',0x3250,6),
                               ('vendor_clock_selector',0x301f,1)):
            values[name]=platform.run(['i2ctransfer','-f','-y',str(bus),'w2@'+addr,
                hex(reg>>8),hex(reg&255),'r'+str(count)])
        result.append(dict(bus=bus,address=addr,values=values))
    return result

def vendor_reset(rows,second,vts,seed_only=False):
    """Diagnostic only: complete reset+vendor HDR init, no slave overlay."""
    defaults=[]
    for bus,addr in ((18,'0x32'),(16,'0x30')):
        for reg,value in ((0x0100,0),(0x0103,1)):
            platform.run(['i2ctransfer','-f','-y',str(bus),'w3@'+addr,
                hex(reg>>8),hex(reg&255),hex(value)])
        time.sleep(.01)
        readings={}
        for reg in (0x3222,0x3223,0x3225,0x3226,0x3227,0x3217,0x3218,0x322b,0x300a):
            readings[hex(reg)]=platform.run(['i2ctransfer','-f','-y',str(bus),
                'w2@'+addr,hex(reg>>8),hex(reg&255),'r1'])
        defaults.append(dict(bus=bus,values=readings))
        writes=[(reg,value) for reg,value in VENDOR_REGS if reg not in (0x0100,0x0103)]
        total=rows*16
        controls=[(0x3812,0),(0x320e,(vts or 4500)>>8),(0x320f,(vts or 4500)&255),
            (0x3e00,(total>>16)&15),(0x3e01,(total>>8)&255),(0x3e02,total&255),
            (0x3e31,second>>8),(0x3e32,second&255),
            (0x5400,(255*(total-second)+total//2)//total),
            (0x3e08,3),(0x3e09,32),(0x3812,0x10),(0x3812,0x60)]
        if not seed_only: writes+=controls
        writes.append((0x0100,1))
        for offset in range(0,len(writes),30):
            args=['i2ctransfer','-f','-y',str(bus)]
            for reg,value in writes[offset:offset+30]:
                args+=['w3@'+addr,hex(reg>>8),hex(reg&255),hex(value)]
            platform.run(args)
    return defaults

def analyze(path):
    blob=path.read_bytes()
    if len(blob)!=COUNT*SIZE: raise RuntimeError('Truncated full RAW')
    packed=np.frombuffer(blob,np.uint8).reshape(COUNT,1280,-1,5)
    pixels=((packed[:,:,:,:4].astype(np.uint16)<<2)|
        ((packed[:,:,:,4,None]>>np.array([0,2,4,6],np.uint8))&3)).reshape(COUNT,1280,1088)
    mean=pixels.mean(axis=0,dtype=np.float32)
    variance=pixels.var(axis=0,dtype=np.float32,ddof=1)
    np.save(path.with_suffix('.mean.npy'),mean)
    np.save(path.with_suffix('.temporal-var.npy'),variance)
    Image.fromarray(np.rint(mean*255/1023).clip(0,255).astype('uint8')).save(path.with_suffix('.mean.png'))
    bands=[]
    for y in range(0,1280,128):
        crop=mean[y:y+128]
        var=variance[y:y+128]
        phase_means=[float(crop[dy::2,dx::2].mean()) for dy,dx in ((0,0),(0,1),(1,0),(1,1))]
        centered=crop.copy()
        for (dy,dx),value in zip(((0,0),(0,1),(1,0),(1,1)),phase_means):
            centered[dy::2,dx::2]-=value
        fixed_rms=float(np.sqrt(max(0,float(centered.var())-float(var.mean())/COUNT)))
        hp=centered[:,2:]-2*centered[:,1:-1]+centered[:,:-2]
        same_phase=(crop[:,4:]-2*crop[:,2:-2]+crop[:,:-4])
        cells=np.stack([crop[0::2,0::2],crop[0::2,1::2],crop[1::2,0::2],crop[1::2,1::2]],axis=-1)
        bands.append(dict(row=y,mean=float(crop.mean()),median=float(np.median(crop)),
            p01=float(np.percentile(crop,1)),p99=float(np.percentile(crop,99)),
            phase_means=phase_means,spatial_std=float(crop.std()),
            temporal_rms=float(np.sqrt(var.mean())),phase_centered_fixed_rms=fixed_rms,
            same_phase_hp_median=float(np.median(np.abs(same_phase))/2),
            cell_spread_median=float(np.median(np.ptp(cells,axis=-1)))))
    hashes=[hashlib.sha256(blob[i*SIZE:(i+1)*SIZE]).hexdigest() for i in range(COUNT)]
    return dict(frames=COUNT,unique_frames=len(set(hashes)),sha256=hashes,
        global_mean=float(mean.mean()),global_median=float(np.median(mean)),
        global_p99=float(np.percentile(mean,99)),bands=bands)

with open('/run/sc132gs-camera.lock','a') as lock,open('/run/sc132gs-mode.lock','a') as legacy:
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    fcntl.flock(legacy,fcntl.LOCK_EX|fcntl.LOCK_NB)
    initial=platform.inspect()
    previous=platform.configuration_from_state(initial)
    durable=platform.DURABLE.read_bytes(); runtime=platform.STATE.read_bytes()
    (OUT/'before-settings.yaml').write_bytes(durable)
    record=dict(purpose=('Human confirmed opaque covers' if covered else 'Uncovered static scene')+
                ', full packed RAW before processing',
                initial=initial,cases=[],restored=False)
    generator=None; captures=[]; handles=[]
    try:
        for name,mode,fps,rows,free,second,vts,gain,hdrc in CASES:
            directory=OUT/name; directory.mkdir()
            config=dict(previous,mode=mode,binning=0,fps=fps,max_fps=fps,ae=0,rows=rows,gain=gain)
            platform.stop(); platform.configure_profile(config)
            if mode=='hdr':
                for node in platform.nodes():
                    platform.run(['v4l2-ctl','-d',node,'--set-ctrl='
                        'hdr_total_nominal_rows='+str(rows)+',hdr_total_second_ratio=256,hdr_second_exposure_ticks='+str(second)+',analogue_gain='+str(gain)])
            platform.run(['/usr/local/sbin/prepare-sc132gs-sync-gpios'])
            log=(directory/'fsync.log').open('w'); handles.append(log)
            no_source=free_static and free
            command=([str(ROOT/'hold-fsync-input')] if no_source else
                ['/usr/local/bin/sc132gs-fsync-generator','auto','18','19',str(fps),'100','active-low'])
            generator=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT)
            deadline=time.monotonic()+5
            ready='FSYNC source disabled' if no_source else 'FSYNC generator armed'
            while ready not in (directory/'fsync.log').read_text():
                if generator.poll() is not None or time.monotonic()>deadline: raise RuntimeError('FSYNC arm')
                time.sleep(.05)
            if not no_source: generator.send_signal(signal.SIGUSR1)
            started=time.monotonic()
            for eye in range(2):
                log=(directory/f'eye{eye}.log').open('w'); handles.append(log)
                node=platform.run(['/usr/local/sbin/sc132gs-discover','cam'+str(eye)])
                captures.append(subprocess.Popen(['v4l2-ctl','-d',node,'--verbose','--stream-mmap=4','--stream-poll',
                    '--stream-skip='+str(32 if vendor or claims or free30 or free_static else 8),'--stream-count='+str(COUNT),'--stream-to='+str(directory/f'eye{eye}.raw')],stdout=log,stderr=subprocess.STDOUT))
            time.sleep(.35)
            reset_defaults=vendor_reset(rows,second,vts,name=='no-fsync-vendor-seed30') if name.startswith(('vendor-reset','no-fsync-vendor')) else []
            diagnostic_register_action='none'
            if name=='claims-blc-reenable':
                # V2.6 p32 explicitly defines 3902[6] as auto BLC enable.
                # Toggle only that bit; this is not proof of a calibration-reset
                # mechanism. Do not assign semantics to undocumented 3933/34.
                for bus,addr in ((18,'0x32'),(16,'0x30')):
                    current=int(platform.run(['i2ctransfer','-f','-y',str(bus),
                        'w2@'+addr,'0x39','0x02','r1']),16)
                    if not current&0x40: raise RuntimeError('Auto BLC initially disabled')
                    for value in (current&~0x40,current):
                        platform.run(['i2ctransfer','-f','-y',str(bus),
                            'w3@'+addr,'0x39','0x02',hex(value)])
                        time.sleep(.05)
                diagnostic_register_action='3902 auto BLC off then on; all other bits preserved'
            if name=='claims-short-gain1x':
                # V2.6 pp23-26 lists HDR short analogue/fine and digital/fine
                # gain. Test its documented 1x tuple, without assuming these
                # registers are active in the vendor single-frame HDR path.
                for bus,addr in ((18,'0x32'),(16,'0x30')):
                    control=int(platform.run(['i2ctransfer','-f','-y',str(bus),
                        'w2@'+addr,'0x3e','0x03','r1']),16)
                    if control&15!=11: raise RuntimeError('Unexpected gain control mode')
                    for payload in (['0x38','0x12','0x00'],
                            ['0x3e','0x10','0x00','0x80','0x03','0x20'],
                            ['0x38','0x12','0x10'],['0x38','0x12','0x60']):
                        platform.run(['i2ctransfer','-f','-y',str(bus),
                            'w'+str(len(payload))+'@'+addr,*payload])
                diagnostic_register_action='short gain 3e10..13 = 00 80 03 20'
            if not hdrc:
                # Datasheet table 2-9: disable the calibration and its extra
                # point read together. HDR response and external trigger stay on.
                for bus,addr in ((18,'0x32'),(16,'0x30')):
                    for payload in (['0x38','0x12','0x00'],
                            ['0x50','0x01','0x00'],['0x32','0x22','0x02'],
                            ['0x38','0x12','0x10'],['0x38','0x12','0x60']):
                        platform.run(['i2ctransfer','-f','-y',str(bus),
                            'w'+str(len(payload))+'@'+addr,*payload])
            if vts:
                # Datasheet table 2-13 documents VTS. Stage both bytes using
                # the same group-0 sequence as the driver's exposure writes.
                for bus,addr in ((18,'0x32'),(16,'0x30')):
                    for payload in (['0x38','0x12','0x00'],
                            ['0x32','0x0e',hex(vts>>8),hex(vts&255)],
                            ['0x38','0x12','0x10'],['0x38','0x12','0x60']):
                        platform.run(['i2ctransfer','-f','-y',str(bus),
                            'w'+str(len(payload))+'@'+addr,*payload])
            if free and name!='no-fsync-vendor-seed30':
                for bus,addr in ((18,'0x32'),(16,'0x30')):
                    platform.run(['i2ctransfer','-f','-y',str(bus),'w3@'+addr,'0x32','0x22','0x30'])
            fsync_stopped=False
            if free30 and free:
                # Prove autonomous frames continue with no running trigger
                # generator. Transition to free-run first, then stop FSYNC.
                finish(generator); generator=None; fsync_stopped=True
            readings=registers()
            for capture in captures:
                if capture.wait(timeout=15): raise RuntimeError('RAW capture failure')
            elapsed=time.monotonic()-started
            finish(generator); generator=None; captures=[]
            for handle in handles: handle.close()
            handles=[]
            item=dict(name=name,configuration=config,diagnostic_free_run=free,
                second_ticks=second,diagnostic_vts=vts,diagnostic_hdrc=hdrc,
                vendor_reset_defaults=reset_defaults,
                diagnostic_register_action=diagnostic_register_action,
                fsync_stopped_for_free_run=fsync_stopped,
                fsync_gpio_input_no_source=no_source,
                capture_wall_seconds=elapsed,registers=readings)
            try:
                item['eyes']=[analyze(directory/f'eye{eye}.raw') for eye in range(2)]
            except RuntimeError as error:
                if not free_static: raise
                item['capture_error']=repr(error)
                item['raw_sizes']=[(directory/f'eye{eye}.raw').stat().st_size for eye in range(2)]
            record['cases'].append(item)
            (OUT/'comparison.json').write_text(json.dumps(record,indent=2)+'\n')
            print(name,[(eye['global_median'],eye['global_p99']) for eye in item.get('eyes',[])] or item.get('capture_error'),flush=True)
    except BaseException as error:
        record['error']=repr(error)
        raise
    finally:
        for capture in captures: finish(capture)
        finish(generator)
        for handle in handles: handle.close()
        platform.stop(); platform.configure_profile(previous); platform.start(previous)
        platform.apply_exposure(previous); platform.verify(previous,True)
        if platform.DURABLE.read_bytes()!=durable or platform.STATE.read_bytes()!=runtime:
            raise RuntimeError('Saved camera policy changed')
        record['restored']=True; record['after']=platform.inspect()
        (OUT/'comparison.json').write_text(json.dumps(record,indent=2)+'\n')
        print('Original HDR AE policy and decoded stream restored',flush=True)
