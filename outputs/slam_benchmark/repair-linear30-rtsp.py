"""Use the already measured 60-trigger/30-frame full-resolution Linear profile."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

base = Path('/home/ubuntu/ros2_humble_ws/slam_benchmark')
root = base / 'rtsp-30fps-10mbps-20261014'
script = Path('/home/ubuntu/stereo-h265-rtsp/run-stereo-rtsp.sh')
shutil.copyfile(script, root / 'run-stereo-before.sh')
original = script.read_text()
needle = 'FSYNC_LOG=${FSYNC_LOG:-/tmp/sc132gs-rtsp-fsync.log}\n'
assert original.count(needle) == 1 and 'SYNC_FPS=' not in original
addition = '''
# Deployed full-resolution Linear 30 profile: 60 GPIO edge requests produce 30 frames/s.
# Keep the requested server/encoder FPS at 30; other profiles retain their existing trigger rate.
SYNC_FPS=$FPS
if [[ $mode_status == 'ok camera_mode=linear '* ]] && (( FPS == 30 )); then
    SYNC_FPS=60
fi
'''
updated = original.replace(needle, needle + addition, 1)
command = '"$FSYNC_BIN" auto 18 19 "$FPS" 100 active-low'
assert updated.count(command) == 1
updated = updated.replace(command, '"$FSYNC_BIN" auto 18 19 "$SYNC_FPS" 100 active-low', 1)
temporary = script.with_name('.run-stereo-rtsp-linear30.tmp')
assert not temporary.exists()
metadata = script.stat()
temporary.write_text(updated)
os.chmod(temporary, metadata.st_mode & 0o7777)
os.chown(temporary, metadata.st_uid, metadata.st_gid)
subprocess.run(['bash', '-n', str(temporary)], check=True)
os.replace(temporary, script)
applied = subprocess.run(['/usr/local/bin/sc132gs-camera', 'apply', '--max-fps', '30'],
                         capture_output=True, text=True, timeout=140)
(root / 'apply-linear30-trigger.json').write_text(json.dumps(dict(returncode=applied.returncode,
    stdout=applied.stdout, stderr=applied.stderr), indent=2) + '\n')
applied.check_returncode()
after = subprocess.run(['python3', str(base / 'inspect-delivery-board.py')], capture_output=True, text=True, check=True)
state = json.loads(after.stdout)
(root / 'after.json').write_text(json.dumps(state, indent=2) + '\n')
status = state['camera_status']['stdout']
assert 'max_fps=30' in status and 'effective_fps=30' in status
processes = [item for item in state['processes'] if item['comm'].startswith('stereo-h265')]
assert len(processes) == 1 and '--fps 30 ' in processes[0]['args'] and '--bitrate 10000000 ' in processes[0]['args']
for source, destination in [(script, 'run-stereo-after.sh'),
    (Path('/home/ubuntu/stereo-h265-rtsp/run-camera-profile.sh'), 'profile-after.sh'),
    (Path('/var/lib/sc132gs-camera/settings.yaml'), 'settings-after.yaml')]:
    shutil.copyfile(source, root / destination)
result = dict(status='configured_decode_pending', requested_fps=30, target_bitrate_bits_per_second=10000000,
    camera_status=status, live_arguments=processes[0]['args'],
    trigger_requested_hz=60, output_requested_fps=30, physical_exposure_synchronization_proven=False,
    persistent_profile_sha256=hashlib.sha256(script.read_bytes()).hexdigest())
(root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result), flush=True)
