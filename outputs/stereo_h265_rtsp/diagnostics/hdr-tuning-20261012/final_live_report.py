"""Record installed artifacts and the final decoded live camera policy."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
sys.path.insert(0,'/home/ubuntu/stereo-h265-rtsp')
import camera_platform as platform

root=Path('/home/ubuntu/hdr-tuning-20261012')
out=root/'final-hdr15-target30'
report={'camera_status':platform.run(['sc132gs-camera','status']),
        'ae_status':platform.run(['sc132gs-ctl','status']),
        'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        'kernel':platform.run(['uname','-r']),
        'decoded':json.loads((out/'decode.json').read_text()),
        'durable':platform.load_durable(platform.DURABLE),
        'runtime':json.loads(platform.STATE.read_text()),
        'control_readbacks':{},'artifact_hashes':{}}
for node in platform.nodes():
    report['control_readbacks'][node]=platform.run(['v4l2-ctl','-d',node,'--get-ctrl='
        'wide_dynamic_range,hdr_total_nominal_rows,hdr_second_exposure_ticks,analogue_gain'])
for path in (Path('/lib/modules')/report['kernel']/'extra/sc132gs.ko',
             Path('/home/ubuntu/stereo-h265-rtsp/build-main10/stereo-h265-rtsp'),
             Path('/usr/local/bin/sc132gs-camera'),Path('/home/ubuntu/stereo-h265-rtsp/camera_platform.py')):
    report['artifact_hashes'][str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
if report['durable']!=report['runtime']: raise RuntimeError('Persisted/runtime policy differs')
status=dict(item.split('=',1) for item in report['ae_status'].split()[1:])
if status['camera_mode']!='hdr' or status['target_percent']!='30' or status['mode']!='auto':
    raise RuntimeError('Final HDR AE policy mismatch')
if int(status['error_errno']) or report['decoded']['decoded_frames']<100:
    raise RuntimeError('Final live proof failed')
(out/'settings.yaml').write_bytes(platform.DURABLE.read_bytes())
(out/'server.log').write_bytes(Path('/run/sc132gs-camera-server.log').read_bytes())
(out/'proof.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report),flush=True)
