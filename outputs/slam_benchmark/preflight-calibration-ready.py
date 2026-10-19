"""Preserve live board evidence and normalize an unowned failed service for capture."""
import json
from pathlib import Path
import subprocess
import time

base = Path('/home/ubuntu/ros2_humble_ws/slam_benchmark')
root = base / 'calibration-ready-20261014'
root.mkdir(exist_ok=True)

def run(command):
    result = subprocess.run(command, capture_output=True, text=True, timeout=20)
    return dict(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)

snapshot = run(['python3', str(base / 'inspect-delivery-board.py')])
assert snapshot['returncode'] == 0
before = json.loads(snapshot['stdout'])
if not (root / 'before.json').exists():
    (root / 'before.json').write_text(json.dumps(before, indent=2))
    (root / 'service-journal.txt').write_text(run(['journalctl', '-u', 'sc132gs-camera-rtsp', '-n', '100', '--no-pager'])['stdout'])
    (root / 'kernel-before.txt').write_text(run(['journalctl', '-k', '-n', '200', '--no-pager'])['stdout'])
owners = run(['fuser', '/dev/video0', '/dev/video3', '/dev/i2c-18', '/dev/i2c-16'])
(root / 'owners.json').write_text(json.dumps(owners, indent=2))
assert not owners['stdout'].strip(), 'Device owner detected; do not interrupt it'
assert not [p for p in before['processes'] if p['comm'].startswith(('stereo-h265', 'sc132gs-fsync', 'gs130wi-imu', 'ros_replay', 'native_replay'))]
service = before['service']['stdout']
assert 'ActiveState=inactive' in service or 'ActiveState=failed' in service, 'Running service not covered by this preflight'
action = 'preserve_inactive'
if 'ActiveState=failed' in service:
    stopped = run(['systemctl', 'stop', 'sc132gs-camera-rtsp'])
    assert stopped['returncode'] == 0, stopped
    action = 'saved_failed_service_logs_then_stopped_without_restart'
after = json.loads(run(['python3', str(base / 'inspect-delivery-board.py')])['stdout'])
if 'ActiveState=failed' in after['service']['stdout']:
    cleared = run(['systemctl', 'reset-failed', 'sc132gs-camera-rtsp'])
    assert cleared['returncode'] == 0, cleared
    action = 'saved_failed_service_logs_then_cleared_failure_without_restart'
    after = json.loads(run(['python3', str(base / 'inspect-delivery-board.py')])['stdout'])
assert before['files'] == after['files']
assert 'ActiveState=inactive' in after['service']['stdout']
(root / 'after-preflight.json').write_text(json.dumps(after, indent=2))
(root / 'preflight.json').write_text(json.dumps(dict(action=action, saved_settings_unchanged=True,
    service_now_inactive=True, timestamp=time.time()), indent=2))
print(json.dumps(dict(action=action, saved_settings_unchanged=True, service_now_inactive=True)))
