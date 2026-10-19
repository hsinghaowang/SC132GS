"""Install the validated HDR control range and owner budget, with rollback."""
raise SystemExit('Obsolete hot-reload attempt; use stage_long_hdr_boot.py and reboot after the other build completes.')
import importlib
from pathlib import Path
import shutil
import subprocess
import sys
sys.path.insert(0,'/home/ubuntu/stereo-h265-rtsp')
import camera_platform as platform

root=Path('/home/ubuntu/hdr-tuning-20261012')
backup=root/'before-long-hdr'
backup.mkdir(exist_ok=False)
kernel=subprocess.check_output(['uname','-r'],text=True).strip()
driver=Path('/lib/modules')/kernel/'extra/sc132gs.ko'
server=Path('/home/ubuntu/stereo-h265-rtsp/build-main10/stereo-h265-rtsp')
cli=Path('/usr/local/bin/sc132gs-camera')
adapter=Path('/home/ubuntu/stereo-h265-rtsp/camera_platform.py')
changes=[(driver,root/'source/sc132gs_v4l2_probe/sc132gs.ko','sc132gs.ko'),
         (server,root/'build/stereo-h265-rtsp','stereo-h265-rtsp'),
         (cli,root/'build/sc132gs-camera','sc132gs-camera'),
         (adapter,root/'source/stereo_h265_rtsp/camera_platform.py','camera_platform.py')]
durable=platform.DURABLE.read_bytes()
for target,source,name in changes: shutil.copy2(target,backup/name)
(backup/'settings.yaml').write_bytes(durable)
try:
    platform.stop()
    subprocess.run(['modprobe','-r','sc132gs'],check=True,timeout=15)
    for target,source,name in changes: shutil.copy2(source,target)
    subprocess.run(['depmod','-a'],check=True,timeout=20)
    subprocess.run(['modprobe','sc132gs'],check=True,timeout=15)
    subprocess.run(['python3',str(adapter),'restore'],check=True,timeout=70)
    if platform.DURABLE.read_bytes()!=durable: raise RuntimeError('Saved policy changed')
    print('Long-HDR driver and AE installed; saved policy restored with decoded RTSP proof')
except BaseException:
    platform.stop()
    subprocess.run(['modprobe','-r','sc132gs'],check=True,timeout=15)
    for target,source,name in changes: shutil.copy2(backup/name,target)
    subprocess.run(['depmod','-a'],check=True,timeout=20)
    subprocess.run(['modprobe','sc132gs'],check=True,timeout=15)
    subprocess.run(['python3',str(adapter),'restore'],check=True,timeout=70)
    raise
