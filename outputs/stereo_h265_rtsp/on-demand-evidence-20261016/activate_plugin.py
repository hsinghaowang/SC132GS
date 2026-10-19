from pathlib import Path
import hashlib,json,subprocess
R=Path('/home/ubuntu/rtsp-demand-20261016')
d=Path('/etc/systemd/system/sc132gs-camera-rtsp.service.d/99-on-demand.conf')
m=json.loads((R/'deployment.json').read_text());assert hashlib.sha256(d.read_bytes()).hexdigest()==m['drop_sha256']
assert '[100%] Built target stereo-h265-rtsp' in (R/'rebuild-v3.log').read_text()
assert (R/'plugin-build.json').exists()
subprocess.run(['systemctl','stop','sc132gs-camera-rtsp.service'],check=True)
(R/'diagnostics-pool-leak.log').write_bytes(Path('/run/sc132gs-camera-server.log').read_bytes())
x=Path('/run/systemd/system/sc132gs-camera-rtsp.service.d/100-demand-debug.conf');assert 'GST_TRACERS=leaks' in x.read_text();x.unlink()
s=d.read_text()+ 'Environment="GST_PLUGIN_PATH='+str(R/'plugin-build/sys/v4l2')+'" "GST_REGISTRY='+str(R/'registry.bin')+'"\n'
d.write_text(s)
p=R/'run-camera-profile.sh';p.write_text(p.read_text().replace('    flowing=$demand\n    for ((attempt=0; attempt<200; ++attempt)); do\n','    flowing=$demand\n    for ((attempt=0; attempt<200; ++attempt)); do\n        if ((flowing)); then break; fi\n'))
m.update(drop_sha256=hashlib.sha256(d.read_bytes()).hexdigest(),binary_sha256=hashlib.sha256((R/'build/stereo-h265-rtsp').read_bytes()).hexdigest(),plugin=json.loads((R/'plugin-build.json').read_text()))
(R/'deployment.json').write_text(json.dumps(m,indent=2))
subprocess.run(['systemctl','daemon-reload'],check=True);subprocess.run(['systemctl','start','sc132gs-camera-rtsp.service'],check=True)
