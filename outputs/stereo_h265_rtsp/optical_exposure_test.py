#!/usr/bin/env python3
"""Exclusive, reversible optical test using RAW10 and the onboard LED."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import random
import signal
import subprocess
import time
import camera_platform as platform

ROOT=Path(__file__).resolve().parent

def interrupted(signum,frame):
    raise KeyboardInterrupt('signal '+str(signum))

def finish(process):
    if process is not None and process.poll() is None:
        process.terminate()
        try: process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(timeout=5)

def run_test(args):
    if os.geteuid()!=0: raise PermissionError('root required for camera/LED resources')
    output=args.output.resolve()
    output.mkdir(parents=True,exist_ok=False)
    led_paths=[Path('/sys/class/leds')/colour for colour in ('red','green','blue')]
    leds=[dict(path=str(path),brightness=(path/'brightness').read_text().strip(),
        trigger=(path/'trigger').read_text().split('[')[1].split(']')[0]) for path in led_paths]
    maximum=int((led_paths[0]/'max_brightness').read_text())
    generator=capture=None
    record=dict(status='starting',output=str(output),leds=leds,
        timestamp_semantics='receiver completion; LED writes are software diagnostics, not measured light edges',
        estimate_semantics='conditional optical integration model; uncalibrated')
    with open('/run/sc132gs-camera.lock','a') as lock,open('/run/sc132gs-mode.lock','a') as legacy:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        fcntl.flock(legacy,fcntl.LOCK_EX|fcntl.LOCK_NB)
        prior=platform.inspect()
        durable_before=platform.DURABLE.read_bytes()
        runtime_before=platform.STATE.read_bytes()
        record['saved_sha256_before']=dict(yaml=hashlib.sha256(durable_before).hexdigest(),
            runtime=hashlib.sha256(runtime_before).hexdigest())
        previous=platform.configuration_from_state(prior)
        record['before']=prior
        test=dict(mode='linear',binning=0,max_fps=args.fps,fps=args.fps,ae=0,brightness=40,
            rows=round(args.exposure_us*84000/1000000),gain=0,max_exposure_us=0,max_gain_index=128)
        record['test']=test
        record['requested_duration_seconds']=args.seconds
        record['nominal_exposure_us']=test['rows']*1000000/84000
        journal=output/'transaction.json'
        journal.write_text(json.dumps(record,indent=2))
        try:
            print('Preparing fixed-exposure RAW capture',flush=True)
            platform.stop()
            platform.configure_profile(test)
            for node in platform.nodes():
                platform.run(['v4l2-ctl','-d',node,'--set-ctrl=exposure='+str(test['rows'])+',analogue_gain=0'])
            for path in led_paths:
                (path/'trigger').write_text('none')
                (path/'brightness').write_text('0')
            platform.run(['/usr/local/sbin/prepare-sc132gs-sync-gpios'])
            with (output/'fsync.log').open('w') as log:
                generator=subprocess.Popen(['/usr/local/bin/sc132gs-fsync-generator','auto','18','19',str(args.fps),'100','active-low'],stdout=log,stderr=subprocess.STDOUT)
            deadline=time.monotonic()+5
            while 'FSYNC generator armed' not in (output/'fsync.log').read_text():
                if generator.poll() is not None or time.monotonic()>deadline: raise RuntimeError('FSYNC did not arm')
                time.sleep(.05)
            generator.send_signal(signal.SIGUSR1)
            devices=[platform.run(['/usr/local/sbin/sc132gs-discover',eye]) for eye in ('cam0','cam1')]
            record['devices']=devices
            with (output/'capture.log').open('w') as log:
                capture=subprocess.Popen([str(ROOT/'build-exposure60/optical-raw-capture'),*devices,str(output),str(args.seconds)],stdout=log,stderr=subprocess.STDOUT)
            deadline=time.monotonic()+8
            while not (output/'capture-ready.json').exists():
                if capture.poll() is not None or time.monotonic()>deadline: raise RuntimeError('RAW capture did not start')
                time.sleep(.05)
            if args.fps==60:
                # Same post-STREAMON profile used by the production capture.
                # The base external-trigger table only accepts 30 FPS.
                for client in platform.CLIENTS:
                    (Path('/sys/bus/i2c/devices')/client/'trigger_60fps').write_text('1\n')
                record['post_stream_high_rate_profile_applied']=True
                time.sleep(.3)
            controls=[]
            for node in platform.nodes():
                text=platform.run(['v4l2-ctl','-d',node,'--get-ctrl=exposure,analogue_gain,wide_dynamic_range'])
                values={line.split(':')[0].strip():int(line.split(':')[1]) for line in text.splitlines()}
                if values!={'exposure':test['rows'],'analogue_gain':0,'wide_dynamic_range':0}:
                    raise RuntimeError('manual controls did not match: '+repr(values))
                controls.append(values)
            record['controls']=controls
            print('RAW capture ready; calibrating LED',flush=True)
            randomizer=random.Random(132)
            started=time.monotonic()
            with (output/'led-events.jsonl').open('w') as events:
                def change(value,stage):
                    before=time.monotonic_ns()
                    (led_paths[0]/'brightness').write_text(str(value))
                    event=dict(before_ns=before,after_ns=time.monotonic_ns(),value=value,stage=stage)
                    events.write(json.dumps(event)+'\n'); events.flush()
                change(0,'calibration_dark'); time.sleep(1.2)
                change(maximum,'calibration_light'); time.sleep(1.2)
                change(0,'calibration_dark2'); time.sleep(1.2)
                print('Collecting optical transitions',flush=True)
                value=0
                while capture.poll() is None and time.monotonic()-started<args.seconds-1:
                    value=maximum if value==0 else 0
                    change(value,'transition')
                    # Incommensurate/random holds sweep phase without assuming
                    # userspace write timing is an electrical/optical edge.
                    time.sleep(randomizer.uniform(.07,.14))
                change(0,'finished')
            returncode=capture.wait(timeout=8)
            if returncode: raise RuntimeError('RAW capture failed: '+str(returncode))
            record['status']='captured'
        except BaseException as error:
            record['status']='capture_failed'
            record['failure']=repr(error)
            raise
        finally:
            for signum in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):
                signal.signal(signum,signal.SIG_IGN)
            print('Restoring camera and LED settings',flush=True)
            restore_errors=[]
            for name,process in (('RAW capture',capture),('FSYNC',generator)):
                try: finish(process)
                except BaseException as error: restore_errors.append(name+' shutdown: '+repr(error))
            for led in leds:
                try:
                    path=Path(led['path'])
                    (path/'brightness').write_text(led['brightness'])
                    (path/'trigger').write_text(led['trigger'])
                    restored_trigger=(path/'trigger').read_text().split('[')[1].split(']')[0]
                    if restored_trigger!=led['trigger']:
                        raise RuntimeError('LED trigger restoration mismatch')
                    if restored_trigger=='none' and (path/'brightness').read_text().strip()!=led['brightness']:
                        raise RuntimeError('LED brightness restoration mismatch')
                except BaseException as error: restore_errors.append('LED: '+repr(error))
            record['restore_attempts']=[]
            record['restored']=False
            for attempt in range(3):
                try:
                    restore_config=previous
                    if attempt and previous['ae']:
                        # AE's changing live values are not policy. Reuse the
                        # original saved startup seed after a transient failure.
                        restore_config=dict(previous)
                        saved=json.loads(runtime_before)
                        restore_config['rows']=saved['rows']; restore_config['gain']=saved['gain']
                    platform.stop()
                    platform.configure_profile(restore_config)
                    platform.start(restore_config)
                    platform.apply_exposure(restore_config)
                    platform.verify(restore_config,True)
                    if platform.DURABLE.read_bytes()!=durable_before or platform.STATE.read_bytes()!=runtime_before:
                        raise RuntimeError('saved settings changed during test')
                    record['after']=platform.inspect()
                    record['restored']=True
                    record['restore_attempts'].append(dict(attempt=attempt+1,success=True))
                    print('Original settings restored and decoded RTSP verified',flush=True)
                    break
                except BaseException as error:
                    record['restore_attempts'].append(dict(attempt=attempt+1,success=False,error=repr(error)))
                    print('Camera restore retry: '+repr(error),flush=True)
            if not record['restored']:
                restore_errors.append('camera: '+record['restore_attempts'][-1]['error'])
            record['restore_errors']=restore_errors
            journal.write_text(json.dumps(record,indent=2))
            if restore_errors: raise RuntimeError('restore failed: '+repr(restore_errors))
    return output

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--seconds',type=int,default=35)
    parser.add_argument('--exposure-us',type=int,default=2000)
    parser.add_argument('--fps',type=int,choices=(30,60),default=30)
    args=parser.parse_args()
    if not 8<=args.seconds<=120 or not 500<=args.exposure_us<=10000: parser.error('seconds 8..120, exposure-us 500..10000')
    for signum in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP): signal.signal(signum,interrupted)
    output=run_test(args)
    subprocess.run(['/usr/bin/python3',str(ROOT/'analyze_optical_exposure.py'),str(output)],check=True)

if __name__=='__main__': main()
