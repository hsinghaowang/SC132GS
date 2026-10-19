"""Authorized RTSP pause, independent bounded capture, and restore in finally."""
import hashlib
import json
from pathlib import Path
import shutil
import signal
import subprocess
import time

base = Path('/home/ubuntu/ros2_humble_ws/slam_benchmark')
root = base / 'stereo-validation-20261014'
retry = root.exists()
assert not (base / 'live-calibration-20261013/target-validation-20261014').exists(), 'Do not replace an existing capture'
if retry:
    for name in ['before.json', 'after.json', 'transaction.json', 'server-before.log', 'fsync-before.log', 'service-before.log']:
        if (root / name).is_file():
            shutil.copyfile(root / name, root / ('attempt1-' + name))
root.mkdir(exist_ok=True)

def run(command, timeout=25):
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    result.check_returncode()
    return result.stdout

def snapshot():
    return json.loads(run(['python3', str(base / 'inspect-delivery-board.py')]))

def save(name, data):
    (root / name).write_text(json.dumps(data, indent=2) + '\n')

def interrupted(signum, frame):
    raise KeyboardInterrupt('signal ' + str(signum))

signal.signal(signal.SIGINT, interrupted)
signal.signal(signal.SIGTERM, interrupted)
before = snapshot()
assert 'ActiveState=active' in before['service']['stdout']
save('before.json', before)
for path, destination in [('/run/sc132gs-camera-server.log', 'server-before.log'),
                          ('/tmp/sc132gs-rtsp-fsync.log', 'fsync-before.log')]:
    if Path(path).is_file():
        shutil.copyfile(path, root / destination)
(root / 'service-before.log').write_text(run(['journalctl', '-u', 'sc132gs-camera-rtsp', '-n', '80', '--no-pager']))
training = base / 'live-calibration-20261013/target-sweep-20261014/geometry-analysis'
for source, destination in [('stereo-candidate.npz', 'frozen-candidate.npz'), ('report.json', 'frozen-training-report.json')]:
    shutil.copyfile(training / source, root / destination)
shutil.copyfile(base / 'factory-calibration-20261013/raw-intrinsics.json', root / 'frozen-intrinsics.json')
shutil.copyfile(Path(__file__), root / Path(__file__).name)
frozen_hash = hashlib.sha256((root / 'frozen-candidate.npz').read_bytes()).hexdigest()
record = dict(session='target-validation-20261014', seconds=60, candidate_frozen_before_new_capture=True,
              frozen_candidate_sha256=frozen_hash, fit_or_update_candidate_allowed=False)
save('transaction.json', record)
child = None
capture_code = None
try:
    run(['systemctl', 'stop', 'sc132gs-camera-rtsp'])
    stopped = snapshot()
    if 'ActiveState=failed' in stopped['service']['stdout']:
        save('stopped-failed-unit.json', stopped)
        run(['systemctl', 'reset-failed', 'sc132gs-camera-rtsp'])
        stopped = snapshot()
    assert 'ActiveState=inactive' in stopped['service']['stdout']
    assert not [p for p in stopped['processes'] if p['comm'].startswith(('stereo-h265', 'sc132gs-fsync', 'gs130wi-imu'))]
    print('RTSP_PAUSED_CAPTURE_STARTS_IN_5_SECONDS', flush=True)
    time.sleep(5)
    with (root / 'capture.log').open('w') as log:
        child = subprocess.Popen(['python3', str(base / 'capture-calibration-session.py'),
                record['session'], '--seconds', '60', '--every', '6', '--gain-index', '0'], stdout=log, stderr=subprocess.STDOUT)
        capture_code = child.wait(timeout=90)
        record['capture_returncode'] = capture_code
        assert capture_code == 0, (root / 'capture.log').read_text()
    print('CAPTURE_COMPLETED_RESTORING_RTSP', flush=True)
except BaseException as error:
    record['error'] = repr(error)
    raise
finally:
    if child is not None and child.poll() is None:
        child.send_signal(signal.SIGTERM)
        try:
            child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)
            record['owned_capture_forced_stop'] = True
    save('transaction.json', record)
    restore = run(['python3', '/home/ubuntu/stereo-h265-rtsp/camera_platform.py', 'restore'], timeout=110)
    (root / 'restore.txt').write_text(restore)
    after = snapshot()
    save('after.json', after)
    record.update(rtsp_active_restored='ActiveState=active' in after['service']['stdout'],
        saved_settings_unchanged=before['files'] == after['files'],
        frozen_candidate_unchanged=frozen_hash == hashlib.sha256((root / 'frozen-candidate.npz').read_bytes()).hexdigest())
    save('transaction.json', record)
    assert record['rtsp_active_restored'] and record['saved_settings_unchanged'] and record['frozen_candidate_unchanged']
print(json.dumps(record), flush=True)
