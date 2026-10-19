"""Install tested user-space defaults with backup/rollback; retain Linear60."""
import fcntl
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
sys.path.insert(0,'/home/ubuntu/stereo-h265-rtsp')
import camera_platform as platform

root=Path('/home/ubuntu/hdr-tuning-20261012')
parser=argparse.ArgumentParser()
parser.add_argument('--viewer-verification', action='store_true',
    help='Verify controls here; require an independent viewer decode afterward')
args=parser.parse_args()
backup=root/('linear60-default-deploy-20261012-viewer' if args.viewer_verification
             else 'linear60-default-deploy-20261012')
backup.mkdir(exist_ok=False)
changes=[
    (Path('/home/ubuntu/stereo-h265-rtsp/build-main10/stereo-h265-rtsp'),root/'build/stereo-h265-rtsp','server'),
    (Path('/usr/local/bin/sc132gs-camera'),root/'build/sc132gs-camera','camera-cli'),
    (Path('/usr/local/bin/sc132gs-ctl'),root/'source/sc132gs_v4l2_probe/sc132gs-ctl','legacy-cli'),
    (Path('/home/ubuntu/stereo-h265-rtsp/run-stereo-rtsp.sh'),root/'source/stereo_h265_rtsp/run-stereo-rtsp.sh','launcher')]
def replace(source,target):
    original=target.stat()
    temporary=target.with_name(target.name+'.linear60-new')
    shutil.copy2(source,temporary)
    os.chown(temporary,original.st_uid,original.st_gid)
    os.replace(temporary,target)

with open('/run/sc132gs-camera.lock','a') as lock,open('/run/sc132gs-mode.lock','a') as legacy:
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    fcntl.flock(legacy,fcntl.LOCK_EX|fcntl.LOCK_NB)
    before=platform.inspect()
    if before['sensor_mode']!='linear' or before['fps']!=60:
        raise RuntimeError('Expected the user-selected Linear60 before installation')
    config=platform.configuration_from_state(before)
    durable=platform.DURABLE.read_bytes(); runtime=platform.STATE.read_bytes()
    (backup/'settings.yaml').write_bytes(durable)
    manifest=dict(before=before,artifacts={})
    for target,source,name in changes:
        shutil.copy2(target,backup/name)
    try:
        platform.stop()
        for target,source,name in changes:
            replace(source,target)
            manifest['artifacts'][str(target)]=dict(
                before=hashlib.sha256((backup/name).read_bytes()).hexdigest(),
                after=hashlib.sha256(target.read_bytes()).hexdigest())
        platform.configure_profile(config); platform.start(config)
        platform.apply_exposure(config); platform.verify(config,not args.viewer_verification)
        if platform.DURABLE.read_bytes()!=durable or platform.STATE.read_bytes()!=runtime:
            raise RuntimeError('User-selected policy changed during installation')
        manifest['after']=platform.inspect()
        manifest['controls_verified']=True
        manifest['board_decode_verified']=not args.viewer_verification
        manifest['viewer_decode_required']=args.viewer_verification
        (backup/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        print('Installed tested binaries; Linear60/AE target30 controls verified')
    except BaseException:
        platform.stop()
        for target,source,name in changes: replace(backup/name,target)
        platform.configure_profile(config); platform.start(config)
        platform.apply_exposure(config); platform.verify(config,not args.viewer_verification)
        raise
