import pathlib
import subprocess
for root in ('/etc/modprobe.d','/etc/modules-load.d','/etc/initramfs-tools','/etc/systemd/system'):
    for path in pathlib.Path(root).rglob('*'):
        if not path.is_file() or path.is_symlink(): continue
        try: content = path.read_text()
        except (UnicodeError,OSError): continue
        if 'sc132gs' in content or 'qcom_camss' in content or 'qcom-camss' in content:
            print('FILE',path, '\n', content[:4000])
print(subprocess.run(['systemctl','list-unit-files','sc132gs*','--no-pager'],capture_output=True,text=True).stdout)
print('RUNTIME CONFIG',pathlib.Path('/run/sc132gs-camera-state.json').read_text())
print('LOADED SRCVERSION',pathlib.Path('/sys/module/sc132gs/srcversion').read_text())
print(subprocess.run(['lsinitramfs','/boot/initrd.img-6.8.0-1084-qcom'],capture_output=True,text=True).stdout.count('sc132gs'))
