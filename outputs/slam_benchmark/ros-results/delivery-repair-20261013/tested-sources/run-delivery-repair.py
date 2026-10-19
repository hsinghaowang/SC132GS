"""Bounded experiment with unchanged binaries; preserve camera-off state."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

base=Path('/home/ubuntu/ros2_humble_ws/slam_benchmark')
evidence=base/'ros-results/delivery-repair-20261013'
parser=argparse.ArgumentParser()
parser.add_argument('mode',choices=('short','full','payload'))
args=parser.parse_args()

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def camera_gate():
    active=[]
    for entry in Path('/proc').glob('[0-9]*/comm'):
        try:
            comm=entry.read_text().strip()
            if comm.startswith(('stereo-h265','sc132gs-fsync','ros_replay','native_replay','cc1','ninja','make')):active.append((entry.parent.name,comm))
        except OSError:pass
    assert not active, f'competing process {active}'
    state=subprocess.run(['systemctl','show','sc132gs-camera-rtsp','-p','ActiveState','-p','SubState','-p','MainPID'],capture_output=True,text=True,check=True).stdout
    assert 'ActiveState=inactive' in state, state
    return dict(service=state,durable_sha256=sha(Path('/var/lib/sc132gs-camera/settings.yaml')),
                runtime_sha256=sha(Path('/run/sc132gs-camera-state.json')),unix_ns=time.time_ns())

before=camera_gate()
if args.mode=='short':
    evidence.mkdir(exist_ok=False)
    (evidence/'before.json').write_text(json.dumps(before,indent=2))
    shutil.copyfile('/var/lib/sc132gs-camera/settings.yaml',evidence/'settings-before.yaml')
    shutil.copyfile('/run/sc132gs-camera-state.json',evidence/'runtime-before.json')
    sources=('native-publisher/ReplayPublisher.hpp','native-publisher/ReplayPublisher.cpp','native-publisher/CMakeLists.txt',
             'native-publisher/build/native_replay_publisher','ros-replay-native.py','ros2-runner/build/ros_replay_receiver',
             'feature-sweep/configs/100/estimator_config.yaml','fastdds-shm-512k.xml','fastdds-shm-4m.xml',
             'run-delivery-trial.sh','run-delivery-repair.py','sample-board-load.py')
    provenance={name:sha(base/name) for name in sources}
    (evidence/'provenance.json').write_text(json.dumps(provenance,indent=2))
    for name in sources:
        target=evidence/'tested-sources'/name
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(base/name,target)
else:
    provenance=json.loads((evidence/'provenance.json').read_text())
assert provenance['native-publisher/build/native_replay_publisher']=='c4d4512df2872f6f4ac62d18a3bf72c20c616ac1856fcd7119f9422e249eb472'
assert provenance['ros2-runner/build/ros_replay_receiver']=='792c66116e2edddcb8877ec7fe488e29047dd38db28ea476306bc7722585b85f'
assert provenance['feature-sweep/configs/100/estimator_config.yaml']=='92b82dce6932b3289c0cd7152068219b87e21c585419908f7ee3558e2b66ec10'
if args.mode=='short':
    cases=[('V2_02_medium','delivery-default-600',600,4,'default'),
           ('V2_02_medium','delivery-shm512-600',600,4,'fastdds-shm-512k.xml'),
           ('V2_02_medium','delivery-shm4m-600',600,4,'fastdds-shm-4m.xml')]
elif args.mode=='full':
    cases=[('MH_01_easy','delivery-shm4m-1',0,4,'fastdds-shm-4m.xml'),
           ('V2_02_medium','delivery-shm4m-1',0,4,'fastdds-shm-4m.xml'),
           ('V2_02_medium','delivery-shm4m-2',0,4,'fastdds-shm-4m.xml'),
           ('MH_01_easy','delivery-shm4m-2',0,4,'fastdds-shm-4m.xml')]
else:
    raise RuntimeError('Payload mode is reserved for independent payload verification')
monitor=subprocess.Popen([sys.executable,str(base/'sample-board-load.py'),str(evidence/(args.mode+'-load.jsonl'))])
closed=threading.Event()
def sample_shm():
    with (evidence/(args.mode+'-shm.jsonl')).open('w') as file:
        while not closed.is_set():
            entries=[]
            for path in Path('/dev/shm').glob('fastrtps*'):
                try:entries.append(dict(name=path.name,size=path.stat().st_size))
                except OSError:pass
            file.write(json.dumps(dict(monotonic_ns=time.monotonic_ns(),segments=entries))+'\n');file.flush()
            closed.wait(1)
sampler=threading.Thread(target=sample_shm);sampler.start()
results=[]
try:
    for dataset,label,frames,prefetch,profile in cases:
        camera_gate()
        assert all(sha(base/name)==digest for name,digest in provenance.items())
        name=dataset+'-paced-'+label
        print('START',name,flush=True)
        begin=time.monotonic_ns()
        with (evidence/(name+'.log')).open('w') as log:
            completed=subprocess.run(['docker','exec','ros2-humble','bash','/ws/slam_benchmark/run-delivery-trial.sh',dataset,name,str(frames),str(prefetch),profile],stdout=log,stderr=subprocess.STDOUT,timeout=310)
        receiver=json.loads((base/'ros-results'/name/'receiver-summary.json').read_text())
        replay=json.loads((base/'ros-results'/name/'replay-summary.json').read_text())
        missing=dict(imu=replay['sent']['imu']-receiver['imu_received'],left=replay['sent']['left']-receiver['left_received'],right=replay['sent']['right']-receiver['right_received'],pairs=replay['sent']['left']-receiver['pairs_received'])
        item=dict(run=name,profile=profile,frames=frames,start_monotonic_ns=begin,end_monotonic_ns=time.monotonic_ns(),returncode=completed.returncode,
                  input_missing=missing,receiver_error=receiver['error_code'],receiver_exit_code=replay['receiver_exit_code'],publisher_exit_code=replay['publisher_exit_code'])
        results.append(item);print(json.dumps(item),flush=True)
        (evidence/(args.mode+'-results.json')).write_text(json.dumps(results,indent=2))
        assert completed.returncode==0
        if profile=='fastdds-shm-4m.xml':assert not any(missing.values()), 'candidate input integrity failed; stop before further testing'
finally:
    closed.set();sampler.join();monitor.terminate();monitor.wait(timeout=5)
    after=camera_gate()
    (evidence/(args.mode+'-after.json')).write_text(json.dumps(after,indent=2))
    assert before['durable_sha256']==after['durable_sha256'] and before['runtime_sha256']==after['runtime_sha256']
print('DELIVERY_BATCH_COMPLETE',args.mode,flush=True)
