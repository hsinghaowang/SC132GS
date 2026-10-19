"""Bounded IMU-only capture with read-only camera state snapshots."""
import hashlib
import json
from pathlib import Path
import subprocess

base=Path('/home/ubuntu/ros2_humble_ws/slam_benchmark')
root=base/'live-calibration-20261013';root.mkdir(exist_ok=True)
assert not (root/'imu-only.csv').exists(), 'preserve earlier capture evidence'
def run(args):
    try:result=subprocess.run(args,capture_output=True,text=True,timeout=20)
    except FileNotFoundError:return dict(returncode=127,stdout='',stderr='Optional inspection command unavailable: '+args[0])
    return dict(returncode=result.returncode,stdout=result.stdout,stderr=result.stderr)
before=run(['python3',str(base/'inspect-delivery-board.py')])
(root/'board-before.json').write_text(before['stdout'])
state=json.loads(before['stdout'])
assert 'ActiveState=inactive' in state['service']['stdout']
gpio=run(['/home/ubuntu/gs130wi-imu/build/gs130wi-imu','--gpio-check','--gpiochip','/dev/gpiochip4','--line','24'])
(root/'gpioinfo.txt').write_text(gpio['stdout']+gpio['stderr'])
probe=run(['i2ctransfer','-y','18','w1@0x68','0x75','r1'])
(root/'whoami.json').write_text(json.dumps(probe,indent=2))
assert probe['returncode']==0 and probe['stdout'].strip()=='0x47'
with (root/'imu-only.csv').open('w') as data,(root/'imu-only-summary.json').open('w') as summary:
    result=subprocess.run(['/home/ubuntu/gs130wi-imu/build/gs130wi-imu','--device','/dev/i2c-18','--gpiochip','/dev/gpiochip4','--line','24','--seconds','30'],stdout=data,stderr=summary,timeout=40)
after=run(['python3',str(base/'inspect-delivery-board.py')])
(root/'board-after-imu.json').write_text(after['stdout'])
last=json.loads(after['stdout'])
assert state['files']==last['files'] and state['service']==last['service']
record=dict(returncode=result.returncode,summary=json.loads((root/'imu-only-summary.json').read_text()),
    camera_saved_state_unchanged=True,imu_binary_sha256=hashlib.sha256(Path('/home/ubuntu/gs130wi-imu/build/gs130wi-imu').read_bytes()).hexdigest())
(root/'imu-probe-result.json').write_text(json.dumps(record,indent=2));print(json.dumps(record),flush=True)
raise SystemExit(result.returncode)
