"""Retain deployed defaults, build provenance and restore verification."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, '/home/ubuntu/stereo-h265-rtsp')
import camera_platform as platform

root = Path('/home/ubuntu/hdr-tuning-20261012')
out = root / 'linear60-default-proof'
out.mkdir(exist_ok=False)
current = platform.inspect()
assert current['sensor_mode'] == 'linear' and current['fps'] == 60
assert current['brightness'] == 30 and current['ae'] == 1 and not current['control_error']
recent = max(Path('/home/ubuntu/sc132gs-camera-tests').glob('apply-*'),
             key=lambda path: path.stat().st_mtime)
for name in ('request.json', 'encoded.json', 'decode.json', 'decoded.png'):
    shutil.copy2(recent / name, out / name)
shutil.copy2(platform.DURABLE, out / 'settings.yaml')
shutil.copy2('/run/sc132gs-camera-server.log', out / 'server.log')
shutil.copy2(root / 'build/Testing/Temporary/LastTest.log', out / 'ctest.log')
artifacts = ['/home/ubuntu/stereo-h265-rtsp/build-main10/stereo-h265-rtsp',
             '/usr/local/bin/sc132gs-camera', '/usr/local/bin/sc132gs-ctl',
             '/home/ubuntu/stereo-h265-rtsp/run-stereo-rtsp.sh',
             '/home/ubuntu/stereo-h265-rtsp/camera_platform.py',
             '/home/ubuntu/stereo-h265-rtsp/verify_rtsp.py',
             '/home/ubuntu/stereo-h265-rtsp/verify_decode_rate.py']
state = dict(state=current, artifacts={path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
                                      for path in artifacts},
             saved=platform.durable_record(),
             driver_hdr=Path('/sys/module/sc132gs/parameters/hdr').read_text().strip(),
             module_defaults=Path('/etc/modprobe.d/sc132gs-external-trigger.conf').read_text(),
             restore_enabled=subprocess.check_output(['systemctl', 'is-enabled',
                                                      'sc132gs-camera-restore.service'], text=True).strip(),
             verification_directory=str(recent),
             reset_verified=True, restore_entry_verified=True, cold_reboot_tested=False)
(out / 'state.json').write_text(json.dumps(state, indent=2) + '\n')
owner = root.stat()
for path in (out, *out.iterdir()):
    shutil.chown(path, user=owner.st_uid, group=owner.st_gid)
print(json.dumps(state))
