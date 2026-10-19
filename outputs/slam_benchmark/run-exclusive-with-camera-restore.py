"""Authorized camera pause, unchanged replay, and guaranteed restoration attempt."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

base = Path('/home/ubuntu/ros2_humble_ws/slam_benchmark')
evidence = base / 'ros-results/camera-pause-restore'
evidence.mkdir(exist_ok=False)
durable = Path('/var/lib/sc132gs-camera/settings.yaml')
platform = '/home/ubuntu/stereo-h265-rtsp/camera_platform.py'
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def run(name, args, timeout=30):
    started = time.time_ns()
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    (evidence / (name + '.txt')).write_text(result.stdout + result.stderr)
    record = dict(started_unix_ns=started, finished_unix_ns=time.time_ns(),
                  arguments=args, returncode=result.returncode)
    (evidence / (name + '.json')).write_text(json.dumps(record, indent=2))
    print(name, result.returncode, result.stdout.strip(), result.stderr.strip(), flush=True)
    result.check_returncode()
    return result.stdout

if os.geteuid() != 0:
    raise RuntimeError('Run under sudo for camera controls and restoration')
for name, path in [('settings.yaml', durable), ('state.json', Path('/run/sc132gs-camera-state.json')),
                   ('server-before.log', Path('/run/sc132gs-camera-server.log')),
                   ('fsync-before.log', Path('/tmp/sc132gs-rtsp-fsync.log'))]:
    shutil.copyfile(path, evidence / name)
saved_hash = sha(durable)
(evidence / 'provenance.json').write_text(json.dumps(dict(
    durable_sha256=saved_hash, platform_sha256=sha(Path(platform)),
    receiver_sha256=sha(base / 'ros2-runner/build/ros_replay_receiver'),
    config_sha256=sha(base / 'feature-sweep/configs/100/estimator_config.yaml')), indent=2))
run('status-before', ['python3', platform, 'status'])
run('service-before', ['systemctl', 'show', 'sc132gs-camera-rtsp', '-p', 'Environment', '-p', 'MainPID', '-p', 'Restart'])
benchmark_returncode = None
try:
    run('stop-camera', ['systemctl', 'stop', 'sc132gs-camera-rtsp'], timeout=25)
    run('owners-after-stop', ['python3', '-c',
        "from pathlib import Path; names=[(p.parent.name,p.read_text().strip()) for p in Path('/proc').glob('[0-9]*/comm') if p.exists()]; camera=[r for r in names if r[1].startswith(('stereo-h265','sc132gs-fsync'))]; print(camera); assert not camera"])
    print('EXCLUSIVE_REPLAY_BEGIN', flush=True)
    result = subprocess.run(['python3', str(base / 'run-exclusive-host.py')])
    benchmark_returncode = result.returncode
finally:
    print('RESTORING_CAMERA', flush=True)
    if sha(durable) != saved_hash:
        raise RuntimeError('Camera settings changed during benchmark; inspect before restoration')
    run('restore-camera', ['python3', platform, 'restore'], timeout=100)
    run('status-after', ['python3', platform, 'status'])
    run('service-after', ['systemctl', 'show', 'sc132gs-camera-rtsp', '-p', 'ActiveState', '-p', 'MainPID'])
    shutil.copyfile('/run/sc132gs-camera-server.log', evidence / 'server-after.log')
    (evidence / 'result.json').write_text(json.dumps(dict(benchmark_returncode=benchmark_returncode,
        restored=True, durable_unchanged=sha(durable)==saved_hash), indent=2))
    print('CAMERA_RESTORED', flush=True)
if benchmark_returncode:
    raise SystemExit(benchmark_returncode)
