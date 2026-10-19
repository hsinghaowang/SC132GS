"""Exclusive bounded image/IMU recording; leave an initially stopped service stopped."""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import signal
import subprocess
import time

base=Path('/home/ubuntu/ros2_humble_ws/slam_benchmark')
parser=argparse.ArgumentParser()
parser.add_argument('name');parser.add_argument('--seconds',type=int,default=10)
parser.add_argument('--every',type=int,default=6)
parser.add_argument('--gain-index',type=int,default=None)
parser.add_argument('--exposure-rows',type=int,default=None)
args=parser.parse_args()
def interrupted(signum,frame):raise KeyboardInterrupt('signal '+str(signum))
signal.signal(signal.SIGINT,interrupted);signal.signal(signal.SIGTERM,interrupted)
if not args.name.replace('-','').replace('_','').isalnum() or not 4<=args.seconds<=180 or not 1<=args.every<=60:parser.error('invalid session options')
if args.gain_index is not None and not 0<=args.gain_index<=128:parser.error('gain index must be 0..128')
if args.exposure_rows is not None and not 1<=args.exposure_rows<=1330:parser.error('exposure rows must be 1..1330')
root=base/'live-calibration-20261013'/args.name;root.mkdir(exist_ok=False)
def run(command):
    result=subprocess.run(command,capture_output=True,text=True,timeout=20)
    result.check_returncode();return result.stdout
def snapshot():return json.loads(run(['python3',str(base/'inspect-delivery-board.py')]))
def finish(process):
    if process and process.poll() is None:
        process.send_signal(signal.SIGTERM)
        try:process.wait(timeout=6)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)
def controls(node):
    return {line.split(':')[0].strip():int(line.split(':')[1]) for line in run(['v4l2-ctl','-d',node,'--get-ctrl=wide_dynamic_range,exposure,analogue_gain']).splitlines()}

record={};generator=camera=imu=None;handles=[]
with open('/run/sc132gs-camera.lock','a') as camera_lock,open('/run/sc132gs-mode.lock','a') as mode_lock:
    fcntl.flock(camera_lock,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(mode_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    before=snapshot()
    assert 'ActiveState=inactive' in before['service']['stdout']
    competing=[p for p in before['processes'] if p['comm'].startswith(('stereo-h265','sc132gs-fsync','gs130wi-imu','ros_replay','native_replay'))]
    assert not competing,competing
    sysclients=[Path('/sys/bus/i2c/devices')/name for name in ('18-0032','16-0030')]
    nodes=['/dev/'+next((p/'video4linux').glob('v4l-subdev*')).name for p in sysclients]
    saved_controls=[controls(node) for node in nodes]
    assert all(value['wide_dynamic_range']==0 for value in saved_controls), 'Only existing Linear mode supported; do not change another mode implicitly'
    record=dict(before=before,saved_driver_controls=saved_controls,nodes=nodes,seconds=args.seconds,select_every_frames=args.every,
                timestamp_scope='Preserve driver V4L2 stamp, dequeue time, IMU-relative counter and batch IRQ/read stamps separately. No exposure/sample synchronization certification.',
                calibration_solved=False,host_sample_time_validated=False)
    (root/'transaction.json').write_text(json.dumps(record,indent=2))
    import shutil
    for source in (base/'calibration-capture').rglob('*'):
        if source.is_file() and ('build' not in source.relative_to(base).parts or source.name=='calibration-capture'):
            target=root/'tested-sources'/source.relative_to(base)
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    shutil.copyfile(Path(__file__),root/'tested-sources/capture-calibration-session.py')
    try:
        # Optional temporary driver controls belong to this transaction and are restored below.
        overrides={}
        if args.gain_index is not None:overrides['analogue_gain']=args.gain_index
        if args.exposure_rows is not None:overrides['exposure']=args.exposure_rows
        if overrides:
            for node in nodes:
                run(['v4l2-ctl','-d',node,'--set-ctrl='+','.join(f'{name}={value}' for name,value in overrides.items())])
            record['temporary_driver_controls']=[controls(node) for node in nodes]
            (root/'transaction.json').write_text(json.dumps(record,indent=2))
        # No durable/profile/AE writes.
        log=(root/'fsync.log').open('w');handles.append(log)
        generator=subprocess.Popen(['/usr/local/bin/sc132gs-fsync-generator','auto','18','19','60','100','active-low'],stdout=log,stderr=subprocess.STDOUT)
        deadline=time.monotonic()+5
        while 'FSYNC generator armed' not in (root/'fsync.log').read_text():
            if generator.poll() is not None or time.monotonic()>deadline:raise RuntimeError('FSYNC did not arm')
            time.sleep(.05)
        generator.send_signal(signal.SIGUSR1)
        imu_data=(root/'imu-raw.csv').open('w');imu_log=(root/'imu-summary.json').open('w');handles.extend((imu_data,imu_log))
        imu=subprocess.Popen(['/home/ubuntu/gs130wi-imu/build/gs130wi-imu','--device','/dev/i2c-18','--gpiochip','/dev/gpiochip4','--line','24','--seconds',str(args.seconds+3)],stdout=imu_data,stderr=imu_log)
        log=(root/'camera.log').open('w');handles.append(log)
        devices=[run(['/usr/local/sbin/sc132gs-discover',name]).strip() for name in ('cam0','cam1')]
        camera=subprocess.Popen([str(base/'calibration-capture/build/calibration-capture'),*devices,str(root),str(args.seconds),str(args.every)],stdout=log,stderr=subprocess.STDOUT)
        camera_code=camera.wait(timeout=args.seconds+12)
        finish(generator);generator=None
        imu_code=imu.wait(timeout=10)
        record.update(camera_returncode=camera_code,imu_returncode=imu_code,devices=devices)
        assert camera_code==0 and imu_code==0, record
    except BaseException as error:
        record['error']=repr(error);raise
    finally:
        finish(camera);finish(imu);finish(generator)
        for handle in handles:handle.close()
        current=[controls(node) for node in nodes]
        for node,saved,actual in zip(nodes,saved_controls,current):
            if actual!=saved:
                run(['v4l2-ctl','-d',node,'--set-ctrl='+','.join(f'{name}={value}' for name,value in saved.items())])
        after=snapshot();record['after']=after;record['driver_controls_after']=[controls(node) for node in nodes]
        record['saved_state_preserved']=before['files']==after['files'] and before['service']==after['service'] and record['driver_controls_after']==saved_controls
        (root/'transaction.json').write_text(json.dumps(record,indent=2))
        assert record['saved_state_preserved']
        for name in ('calibration-capture/build/calibration-capture','calibration-capture/CalibrationCapture.hpp',
                     'calibration-capture/CalibrationCapture.cpp','capture-calibration-session.py'):
            record.setdefault('source_sha256',{})[name]=hashlib.sha256((base/name).read_bytes()).hexdigest()
        (root/'transaction.json').write_text(json.dumps(record,indent=2))
print(json.dumps(dict(camera=json.loads((root/'camera-summary.json').read_text()),imu=json.loads((root/'imu-summary.json').read_text()),saved_state_preserved=record['saved_state_preserved'])),flush=True)
