"""Camera-off gate, platform trace, and immutable-state evidence for publisher A/B."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

base=Path('/home/ubuntu/ros2_humble_ws/slam_benchmark')
root=base/'ros-results/prefetch-comparison-20261013'
root.mkdir(exist_ok=False)
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def snapshot(name):
    camera=[]
    for p in Path('/proc').glob('[0-9]*/comm'):
        try:
            comm=p.read_text().strip()
            if comm.startswith(('stereo-h265','sc132gs-fsync')):camera.append((int(p.parent.name),comm))
        except OSError:pass
    state={}
    for label,args in (
        ('camera_service',['systemctl','show','sc132gs-camera-rtsp','-p','ActiveState','-p','SubState','-p','MainPID']),
        ('camera_status',['/usr/local/bin/sc132gs-camera','status'])):
        completed=subprocess.run(args,capture_output=True,text=True,timeout=10)
        state[label]=dict(returncode=completed.returncode,stdout=completed.stdout,stderr=completed.stderr)
    state.update(camera_processes=camera,durable_sha256=sha('/var/lib/sc132gs-camera/settings.yaml'),
                 runtime_state_sha256=sha('/run/sc132gs-camera-state.json'),unix_ns=time.time_ns())
    (root/(name+'.json')).write_text(json.dumps(state,indent=2))
    return state
before=snapshot('platform-before')
if before['camera_processes']:raise RuntimeError('camera still running; this batch requires camera-off state')
shutil.copyfile('/run/sc132gs-camera-server.log',root/'camera-failure-before.log')
journal=subprocess.run(['journalctl','-u','sc132gs-camera-rtsp','-n','20','--no-pager'],capture_output=True,text=True,timeout=10)
(root/'camera-journal-before.txt').write_text(journal.stdout+journal.stderr)
sources=('native-publisher/ReplayPublisher.hpp','native-publisher/ReplayPublisher.cpp','native-publisher/CMakeLists.txt',
    'native-publisher/build/native_replay_publisher','ros-replay-native.py','ros-replay.py',
    'ros2-runner/build/ros_replay_receiver','feature-sweep/configs/100/estimator_config.yaml',
    'run-prefetch-comparison.sh','run-prefetch-host.py','sample-board-load.py')
(root/'provenance.json').write_text(json.dumps({p:sha(base/p) for p in sources},indent=2))
monitor=subprocess.Popen([sys.executable,str(base/'sample-board-load.py'),str(root/'platform-load.jsonl')])
(root/'monitor.json').write_text(json.dumps(dict(pid=monitor.pid,sampling_interval_s=1),indent=2))
result=None
try:
    time.sleep(3)
    result=subprocess.run(['docker','exec','ros2-humble','bash','/ws/slam_benchmark/run-prefetch-comparison.sh'])
finally:
    monitor.terminate();monitor.wait(timeout=5)
    after=snapshot('platform-after')
    unchanged=(before['durable_sha256']==after['durable_sha256'] and
        before['runtime_state_sha256']==after['runtime_state_sha256'] and not after['camera_processes'])
    (root/'result.json').write_text(json.dumps(dict(returncode=result.returncode if result else None,
        original_camera_off_state_preserved=unchanged),indent=2))
    assert unchanged, 'camera state changed during publisher comparison'
if result.returncode:raise SystemExit(result.returncode)
