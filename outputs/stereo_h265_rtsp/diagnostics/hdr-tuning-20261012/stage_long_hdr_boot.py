"""Stage HDR driver and owner for reboot; never hot-unload CAMSS."""
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
kernel=subprocess.check_output(['uname','-r'],text=True).strip()
source_driver=root/'source/sc132gs_v4l2_probe/sc132gs.ko'
if subprocess.check_output(['modinfo','-F','vermagic',str(source_driver)],text=True).split()[0]!=kernel:
    raise SystemExit('Kernel mismatch')
subprocess.run(['ctest','--test-dir',str(root/'build'),'--output-on-failure'],check=True)
if subprocess.run(['pgrep','-f','^/usr/bin/python3 /usr/bin/colcon build --packages-select ov_core'],capture_output=True).returncode==0:
    raise SystemExit('OpenVINS build still running; defer staging/reboot')
subprocess.run(['systemctl','is-enabled','--quiet','sc132gs-camera-restore.service'],check=True)
backup=root/'long-hdr-boot-stage'
backup.mkdir(exist_ok=False)
driver=Path('/lib/modules')/kernel/'extra/sc132gs.ko'
server=Path('/home/ubuntu/stereo-h265-rtsp/build-main10/stereo-h265-rtsp')
cli=Path('/usr/local/bin/sc132gs-camera')
adapter=Path('/home/ubuntu/stereo-h265-rtsp/camera_platform.py')
changes=[(driver,source_driver,'sc132gs.ko'),
         (server,root/'build/stereo-h265-rtsp','stereo-h265-rtsp'),
         (cli,root/'build/sc132gs-camera','sc132gs-camera'),
         (adapter,root/'source/stereo_h265_rtsp/camera_platform.py','camera_platform.py')]
durable=platform.DURABLE.read_bytes()
for target,source,name in changes: shutil.copy2(target,backup/name)
(backup/'settings.yaml').write_bytes(durable)
manifest={}
try:
    for target,source,name in changes:
        temporary=target.with_name(target.name+'.long-hdr-new')
        shutil.copy2(source,temporary)
        temporary.chmod(0o644 if target==driver else 0o755)
        os.replace(temporary,target)
        manifest[str(target)]=dict(before=hashlib.sha256((backup/name).read_bytes()).hexdigest(),
            after=hashlib.sha256(target.read_bytes()).hexdigest())
    subprocess.run(['depmod','-a',kernel],check=True,timeout=20)
    if platform.DURABLE.read_bytes()!=durable: raise RuntimeError('Saved policy changed')
    (backup/'manifest.json').write_text(json.dumps(manifest,indent=2))
    print('Staged for reboot; loaded sensor and running server retain their current versions')
except BaseException:
    for target,source,name in changes:
        temporary=target.with_name(target.name+'.long-hdr-rollback')
        shutil.copy2(backup/name,temporary)
        os.replace(temporary,target)
    subprocess.run(['depmod','-a',kernel],check=True,timeout=20)
    raise
