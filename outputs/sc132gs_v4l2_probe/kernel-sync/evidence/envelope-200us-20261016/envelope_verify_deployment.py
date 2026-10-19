#!/usr/bin/env python3
"""Read back loaded module, unchanged persistent settings, and restored stream."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path('/home/ubuntu/sc132gs-envelope-200us-20261016')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(args):
    return subprocess.check_output(args, text=True).strip()


manifest = json.loads((ROOT / 'baseline-manifest.json').read_text())
deployed = json.loads((ROOT / 'deployed-manifest.json').read_text())
target = Path('/lib/modules/6.8.0-1084-qcom/updates/sc132gs-csid-monitor/qcom-camss.ko')
loaded = Path('/sys/module/qcom_camss/srcversion').read_text().strip()
boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
unchanged = {name: sha(Path(name)) == entry['sha256'] for name, entry in manifest.items()
             if not name.startswith(('/run/', '/lib/modules/', '/boot/'))}
control = dict(token.split('=', 1) for token in
               Path('/sys/bus/platform/devices/acb3000.camss/fsync_control').read_text().split())
service = command(['systemctl', 'show', 'sc132gs-camera-rtsp.service', '-p', 'MainPID',
                   '-p', 'NRestarts', '-p', 'ActiveState'])
checks = dict(loaded_srcversion_matches=loaded == deployed['module_srcversion'],
              installed_srcversion_matches=command(['modinfo', '-F', 'srcversion', str(target)]) == loaded,
              installed_module_hash_matches=sha(target) == deployed['module_sha256'],
              built_module_hash_matches=sha(ROOT / 'source/qcom-camss.ko') == deployed['module_sha256'],
              source_hash_matches=sha(ROOT / 'source/camss-sync.c') == deployed['source_sha256'],
              reboot_confirmed=boot != (ROOT / 'baseline-boot-id.txt').read_text().strip(),
              persistent_configuration_unchanged=all(unchanged.values()),
              stream_active='ActiveState=active' in service and 'NRestarts=0' in service,
              healthy_sync=all(control.get(key) == value for key, value in
                  dict(running='1', error='0', error_count='0', skipped='0', locked_mask='3').items()))
report = dict(passed=all(checks.values()), checks=checks, module_srcversion=loaded,
              module_sha256=sha(target), source_sha256=deployed['source_sha256'], boot_id=boot,
              envelope_ns=200000, release_overrun_ns=25000,
              unchanged=unchanged, control=control, service=service,
              camera_status=command(['python3', '/home/ubuntu/stereo-h265-rtsp/camera_platform.py', 'status']))
for name, args in {
    'server-after.log': ['journalctl', '-u', 'sc132gs-camera-rtsp.service', '-b', '--no-pager'],
    'kernel-after.log': ['dmesg', '--color=never'],
    'processes-after.txt': ['ps', '-eo', 'pid,ppid,args'],
}.items():
    (ROOT / name).write_text(command(args) + '\n')
(ROOT / 'deployment-readback.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
raise SystemExit(0 if report['passed'] else 1)
