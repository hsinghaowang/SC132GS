#!/usr/bin/env python3
"""Install the already hardware-tested sensor module and boot restore service."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import yaml  # Fail before installation when python3-yaml is missing.

def run(*args):
    return subprocess.check_output(args, text=True).strip()

if os.geteuid()!=0: raise SystemExit('root required')
kernel=run('uname','-r')
source=Path('/home/ubuntu/sc132gs-binning-20261007/sc132gs.ko')
target=Path('/lib/modules')/kernel/'extra/sc132gs.ko'
if run('modinfo','-F','vermagic',str(source)).split()[0]!=kernel:
    raise SystemExit('module kernel mismatch')
if run('modinfo','-F','srcversion',str(source))!=Path('/sys/module/sc132gs/srcversion').read_text().strip():
    raise SystemExit('source differs from the currently tested module')
backup=Path('/var/lib/sc132gs-camera/backups')/kernel
backup.mkdir(parents=True,exist_ok=True)
if not (backup/'sc132gs.ko').exists():
    shutil.copy2(target,backup/'sc132gs.ko')
    (backup/'manifest.json').write_text(json.dumps(dict(kernel=kernel,
        original_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        tested_sha256=hashlib.sha256(source.read_bytes()).hexdigest()),indent=2))
temporary=target.with_suffix('.new')
shutil.copy2(source,temporary)
os.replace(temporary,target)
run('depmod','-a',kernel)
service=Path('/etc/systemd/system/sc132gs-camera-restore.service')
if service.exists() and not (backup/service.name).exists(): shutil.copy2(service,backup/service.name)
service.write_text('''[Unit]
Description=Restore last verified SC132GS stereo camera settings
After=local-fs.target systemd-modules-load.service network-online.target
Wants=network-online.target
RequiresMountsFor=/home/ubuntu/stereo-h265-rtsp /var/lib/sc132gs-camera
StartLimitIntervalSec=0

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /home/ubuntu/stereo-h265-rtsp/camera_platform.py restore
RemainAfterExit=yes
TimeoutStartSec=120
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
''')
run('systemctl','daemon-reload')
run('systemctl','enable','sc132gs-camera-restore.service')
print('installed kernel='+kernel+' srcversion='+run('modinfo','-F','srcversion',str(target)))
print('backup='+str(backup))
