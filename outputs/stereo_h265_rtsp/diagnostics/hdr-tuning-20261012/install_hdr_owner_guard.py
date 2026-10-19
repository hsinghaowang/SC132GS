"""Install the measured HDR owner guard without changing the loaded driver."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
sys.path.insert(0,'/home/ubuntu/stereo-h265-rtsp')
import camera_platform as platform

root=Path('/home/ubuntu/hdr-tuning-20261012')
subprocess.run(['ctest','--test-dir',str(root/'build'),'--output-on-failure'],check=True)
backup=root/(sys.argv[1] if len(sys.argv)>1 else 'long-hdr-4350-stage')
backup.mkdir(exist_ok=False)
changes=[(Path('/home/ubuntu/stereo-h265-rtsp/build-main10/stereo-h265-rtsp'),root/'build/stereo-h265-rtsp'),
         (Path('/usr/local/bin/sc132gs-camera'),root/'build/sc132gs-camera'),
         (Path('/home/ubuntu/stereo-h265-rtsp/camera_platform.py'),root/'source/stereo_h265_rtsp/camera_platform.py')]
durable=platform.DURABLE.read_bytes()
(backup/'settings.yaml').write_bytes(durable)
for target,source in changes: shutil.copy2(target,backup/target.name)
platform.stop()

def replace(target,source):
    temporary=target.with_name(target.name+'.owner-guard-new')
    shutil.copy2(source,temporary)
    temporary.chmod(0o755)
    os.replace(temporary,target)

try:
    for target,source in changes: replace(target,source)
    subprocess.run(['/usr/bin/python3','/home/ubuntu/stereo-h265-rtsp/camera_platform.py','restore'],check=True,timeout=90)
    if platform.DURABLE.read_bytes()!=durable: raise RuntimeError('Saved policy changed')
    (backup/'manifest.json').write_text(json.dumps({str(target):hashlib.sha256(target.read_bytes()).hexdigest()
        for target,source in changes},indent=2))
    print('Measured HDR owner ceiling installed; RTSP and policy restored')
except BaseException:
    platform.stop()
    for target,source in changes: replace(target,backup/target.name)
    subprocess.run(['/usr/bin/python3','/home/ubuntu/stereo-h265-rtsp/camera_platform.py','restore'],check=True,timeout=90)
    raise
