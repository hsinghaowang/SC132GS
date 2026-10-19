#!/usr/bin/env python3
"""Back up the exact current deployment, install a tested module, then reboot separately."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path('/home/ubuntu/sc132gs-stability-20261015')
KERNEL = '6.8.0-1084-qcom'
TARGET = Path('/lib/modules') / KERNEL / 'updates/sc132gs-csid-monitor/qcom-camss.ko'
BACKUP = ROOT / 'backup'
FILES = [TARGET, Path('/boot/initrd.img-' + KERNEL),
         Path('/etc/modprobe.d/sc132gs-csid-monitor.conf'),
         Path('/var/lib/sc132gs-camera/settings.json'), Path('/var/lib/sc132gs-camera/settings.yaml'),
         Path('/home/ubuntu/stereo-h265-rtsp/build-main10/stereo-h265-rtsp'),
         Path('/home/ubuntu/stereo-h265-rtsp/run-camera-profile.sh'),
         Path('/home/ubuntu/stereo-h265-rtsp/run-stereo-rtsp.sh')]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(args):
    return subprocess.check_output(args, text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['save', 'install', 'restore'])
    args = parser.parse_args()
    if command(['uname', '-r']) != KERNEL:
        raise RuntimeError('unexpected kernel')
    if args.action == 'save':
        BACKUP.mkdir(mode=0o700)  # Refuse to overwrite any earlier backup.
        manifest = {}
        for index, path in enumerate(FILES):
            saved = BACKUP / (str(index) + '-' + path.name)
            shutil.copy2(path, saved)
            manifest[str(path)] = {'backup': saved.name, 'sha256': sha(path)}
            assert sha(saved) == manifest[str(path)]['sha256']
        (ROOT / 'baseline-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        (ROOT / 'baseline-status.txt').write_text(Path('/sys/bus/platform/devices/acb3000.camss/fsync_control').read_text())
        (ROOT / 'baseline-boot-id.txt').write_text(Path('/proc/sys/kernel/random/boot_id').read_text())
        (ROOT / 'baseline-source.c').write_bytes(Path('/home/ubuntu/sc132gs-kernel-sync-20261014/source/camss-sync.c').read_bytes())
        (ROOT / 'baseline-match.h').write_bytes(Path('/home/ubuntu/sc132gs-kernel-sync-20261014/source/camss-sync-match.h').read_bytes())
        with (ROOT / 'baseline-events.txt').open('w') as output:
            subprocess.run(['cat', '/sys/kernel/debug/sc132gs_sync/events'], stdout=output, check=True)
        with (ROOT / 'baseline-services.txt').open('w') as output:
            subprocess.run(['systemctl', 'cat', 'sc132gs-camera-rtsp.service', 'sc132gs-camera-restore.service'], stdout=output, check=True)
        print('Verified exact deployment backup; no running driver changed')
        return
    manifest = json.loads((ROOT / 'baseline-manifest.json').read_text())
    for entry in manifest.values():
        assert sha(BACKUP / entry['backup']) == entry['sha256']
    subprocess.run(['systemctl', 'stop', 'sc132gs-camera-restore.service', 'sc132gs-camera-rtsp.service'], check=True)
    Path('/sys/bus/platform/devices/acb3000.camss/fsync_control').write_text('stop\n')
    if args.action == 'install':
        # Fail if any pre-existing module/options/settings changed after backup.
        for path, entry in manifest.items():
            assert sha(Path(path)) == entry['sha256'], path
        for name in ['atomic-fixture', 'publication-fixture', 'association-fixture']:
            result = json.loads((ROOT / name / 'result.json').read_text())
            assert result['passed'] and result['source_sha256'] == sha(ROOT / 'source/camss-sync.c')
        module = ROOT / 'source/qcom-camss.ko'
        assert command(['modinfo', '-F', 'vermagic', str(module)]).startswith(KERNEL + ' ')
        shutil.copy2(module, TARGET)
        subprocess.run(['depmod', '-a', KERNEL], check=True)
        subprocess.run(['update-initramfs', '-u', '-k', KERNEL], check=True)
        (ROOT / 'deployed-manifest.json').write_text(json.dumps({
            'module_sha256': sha(TARGET), 'module_srcversion': command(['modinfo', '-F', 'srcversion', str(TARGET)]),
            'initrd_sha256': sha(Path('/boot/initrd.img-' + KERNEL)),
            'source_sha256': sha(ROOT / 'source/camss-sync.c')}, indent=2) + '\n')
        print('New module installed on disk only. Reboot required; do not hot-unload CAMSS.')
    else:
        for path, entry in manifest.items():
            shutil.copy2(BACKUP / entry['backup'], path)
        subprocess.run(['depmod', '-a', KERNEL], check=True)
        print('Exact prior files restored. Reboot required to restore the running module.')


if __name__ == '__main__':
    main()
