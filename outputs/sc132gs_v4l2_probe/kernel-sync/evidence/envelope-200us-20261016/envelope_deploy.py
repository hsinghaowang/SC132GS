#!/usr/bin/env python3
"""Preserve this deployment, install the bounded-envelope module, reboot separately."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path('/home/ubuntu/sc132gs-envelope-200us-20261016')
KERNEL = '6.8.0-1084-qcom'
TARGET = Path('/lib/modules') / KERNEL / 'updates/sc132gs-csid-monitor/qcom-camss.ko'
CONTROL = Path('/sys/bus/platform/devices/acb3000.camss/fsync_control')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(args):
    return subprocess.check_output(args, text=True).strip()


def main():
    assert command(['uname', '-r']) == KERNEL
    module = ROOT / 'source/qcom-camss.ko'
    source_hash = sha(ROOT / 'source/camss-sync.c')
    for name in ('atomic-fixture', 'publication-fixture', 'association-fixture'):
        result = json.loads((ROOT / name / 'result.json').read_text())
        assert result['passed'] and result['source_sha256'] == source_hash
    limits = json.loads((ROOT / 'atomic-fixture/result.json').read_text())['configuration_ns']
    assert limits['PULSE_ENVELOPE_NS'] == 200000 and limits['PULSE_OVERRUN_NS'] == 25000
    assert command(['modinfo', '-F', 'vermagic', str(module)]).startswith(KERNEL + ' ')
    backup = ROOT / 'backup'
    backup.mkdir(mode=0o700, exist_ok=True)
    paths = [TARGET, Path('/boot/initrd.img-' + KERNEL),
             Path('/etc/modprobe.d/sc132gs-csid-monitor.conf'),
             Path('/var/lib/sc132gs-camera/settings.yaml'),
             Path('/var/lib/sc132gs-camera/settings.json'),
             Path('/home/ubuntu/stereo-h265-rtsp/build-main10/stereo-h265-rtsp'),
             Path('/home/ubuntu/stereo-h265-rtsp/run-camera-profile.sh'),
             Path('/home/ubuntu/stereo-h265-rtsp/run-stereo-rtsp.sh'),
             Path('/run/sc132gs-camera-state.json')]
    manifest_path = ROOT / 'baseline-manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    for index, path in enumerate(paths):
        if not path.exists():
            continue
        if str(path) in manifest:
            assert sha(backup / manifest[str(path)]['backup']) == manifest[str(path)]['sha256']
            continue
        saved = backup / (str(index) + '-' + path.name)
        shutil.copy2(path, saved)
        manifest[str(path)] = dict(backup=saved.name, sha256=sha(path))
        assert sha(saved) == sha(path)
    (ROOT / 'baseline-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    for name, args in {
        'baseline-units.txt': ['systemctl', 'cat', 'sc132gs-camera-restore.service', 'sc132gs-camera-rtsp.service'],
        'baseline-status.txt': ['python3', '/home/ubuntu/stereo-h265-rtsp/camera_platform.py', 'status'],
        'baseline-processes.txt': ['ps', '-eo', 'pid,ppid,args'],
    }.items():
        output = ROOT / name
        if not output.exists():
            result = subprocess.run(args, text=True, capture_output=True)
            output.write_text(result.stdout + result.stderr + '\nexit_code=' + str(result.returncode) + '\n')
    (ROOT / 'baseline-events.txt').write_text(Path('/sys/kernel/debug/sc132gs_sync/events').read_text())
    (ROOT / 'baseline-control.txt').write_text(CONTROL.read_text())
    (ROOT / 'baseline-boot-id.txt').write_text(Path('/proc/sys/kernel/random/boot_id').read_text())
    (ROOT / 'baseline-loaded-srcversion.txt').write_text(Path('/sys/module/qcom_camss/srcversion').read_text())
    subprocess.run(['systemctl', 'stop', 'sc132gs-camera-restore.service', 'sc132gs-camera-rtsp.service'], check=True)
    CONTROL.write_text('stop\n')
    # Revalidate persistent files immediately before replacing the module.
    for path, entry in manifest.items():
        if not path.startswith('/run/'):
            assert sha(Path(path)) == entry['sha256'], path
    shutil.copy2(module, TARGET)
    subprocess.run(['depmod', '-a', KERNEL], check=True)
    subprocess.run(['update-initramfs', '-u', '-k', KERNEL], check=True)
    result = dict(module_sha256=sha(TARGET), source_sha256=source_hash,
                  module_srcversion=command(['modinfo', '-F', 'srcversion', str(TARGET)]),
                  initrd_sha256=sha(Path('/boot/initrd.img-' + KERNEL)),
                  envelope_ns=200000, release_overrun_ns=25000)
    (ROOT / 'deployed-manifest.json').write_text(json.dumps(result, indent=2) + '\n')
    subprocess.run(['sync'], check=True)
    print(json.dumps(result, indent=2))
    print('Installed on disk; reboot required to load. Backup retained for rollback.')


if __name__ == '__main__':
    main()
