"""Save requested FPS through the camera API and bitrate through the RTSP owner profile."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

base = Path('/home/ubuntu/ros2_humble_ws/slam_benchmark')
root = base / 'rtsp-30fps-10mbps-20261014'
root.mkdir(exist_ok=False)
profile = Path('/home/ubuntu/stereo-h265-rtsp/run-camera-profile.sh')

def run(command, timeout=25):
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    return dict(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)

def save(name, value):
    (root / name).write_text(json.dumps(value, indent=2) + '\n')

before = run(['python3', str(base / 'inspect-delivery-board.py')])
assert before['returncode'] == 0
before = json.loads(before['stdout'])
save('before.json', before)
assert 'ActiveState=active' in before['service']['stdout']
for source, destination in [(profile, 'profile-before.sh'),
        (Path('/var/lib/sc132gs-camera/settings.yaml'), 'settings-before.yaml'),
        (Path('/run/sc132gs-camera-state.json'), 'state-before.json'),
        (Path('/run/sc132gs-camera-server.log'), 'server-before.log')]:
    shutil.copyfile(source, root / destination)
original = profile.read_text()
needle = 'HEVC_PROFILE=${HEVC_PROFILE:-main10}\n'
assert original.count(needle) == 1 and 'export BITRATE=' not in original
updated = original.replace(needle, needle + 'export BITRATE=${BITRATE:-10000000}\n', 1)
binning = '--capture-mode linear-binning --hevc-profile "$HEVC_PROFILE"'
assert updated.count(binning) == 1
updated = updated.replace(binning, binning + ' --bitrate "$BITRATE"', 1)
temporary = profile.with_name('.run-camera-profile-30fps-10mbps.tmp')
assert not temporary.exists()
metadata = profile.stat()
temporary.write_text(updated)
os.chmod(temporary, metadata.st_mode & 0o7777)
os.chown(temporary, metadata.st_uid, metadata.st_gid)
syntax = run(['bash', '-n', str(temporary)])
save('syntax-check.json', syntax)
assert syntax['returncode'] == 0
os.replace(temporary, profile)
applied = run(['/usr/local/bin/sc132gs-camera', 'apply', '--max-fps', '30'], timeout=130)
save('apply.json', applied)
if applied['returncode'] != 0:
    save('failure.json', dict(message='FPS apply failed; backups preserved; inspect camera API rollback before another change'))
    raise RuntimeError(applied)
after = run(['python3', str(base / 'inspect-delivery-board.py')])
assert after['returncode'] == 0
after = json.loads(after['stdout'])
save('after.json', after)
assert 'ActiveState=active' in after['service']['stdout']
assert 'max_fps=30' in after['camera_status']['stdout'] and 'effective_fps=30' in after['camera_status']['stdout']
processes = [item for item in after['processes'] if item['comm'].startswith('stereo-h265')]
assert len(processes) == 1
assert '--fps 30 ' in processes[0]['args'] and '--bitrate 10000000 ' in processes[0]['args']
shutil.copyfile(profile, root / 'profile-after.sh')
shutil.copyfile('/var/lib/sc132gs-camera/settings.yaml', root / 'settings-after.yaml')
record = dict(status='configured_live_decode_pending', maximum_fps=30, effective_fps=30,
    target_bitrate_bits_per_second=10000000, profile_persists_bitrate_on_restore=True,
    source_profile_sha256=hashlib.sha256(profile.read_bytes()).hexdigest(),
    live_server_arguments=processes[0]['args'], camera_status=after['camera_status']['stdout'])
save('result.json', record)
print(json.dumps(record), flush=True)
