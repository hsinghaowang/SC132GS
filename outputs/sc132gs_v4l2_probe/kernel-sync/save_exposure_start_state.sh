#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/ubuntu/sc132gs-kernel-sync-20261014
cd "$ROOT"
sha256sum -c backup.sha256 > exposure-start-final-original-backup-verified.txt
sha256sum -c exposure-start-baseline.sha256 > exposure-start-final-backup-verified.txt
sha256sum source/camss-sync.c source/camss-sync.h source/camss-sync-match.h source/camss-video.c source/camss-vfe-17x.c userspace/KernelSyncStatus.cpp userspace/KernelSyncStatus.hpp userspace/StereoCapture.cpp userspace/StereoRtspServer.cpp RawSyncProbe.cpp raw-sync-probe > exposure-start-final-source.sha256
sha256sum /lib/modules/$(uname -r)/updates/sc132gs-csid-monitor/qcom-camss.ko /boot/initrd.img-$(uname -r) /etc/modprobe.d/sc132gs-csid-monitor.conf /var/lib/sc132gs-camera/settings.yaml /home/ubuntu/stereo-h265-rtsp/build-main10/stereo-h265-rtsp /home/ubuntu/stereo-h265-rtsp/run-stereo-rtsp.sh > exposure-start-final-deployed.sha256
cat /sys/module/qcom_camss/srcversion > exposure-start-final-srcversion.txt
cat /sys/bus/platform/devices/acb3000.camss/fsync_control > exposure-start-final-sync-status.txt
sc132gs-ctl status > exposure-start-final-camera-status.txt
systemctl show sc132gs-camera-rtsp.service -p ActiveState -p MainPID -p NRestarts > exposure-start-final-service.txt
cp /run/sc132gs-camera-server.log exposure-start-final-server.log
dmesg --color=never > exposure-start-final-dmesg.txt
python3 - <<'PY'
from pathlib import Path
import json,re
s=dict(t.split('=',1) for t in Path('exposure-start-final-sync-status.txt').read_text().split())
assert s['abi']=='4' and s['source']=='exposure_start_estimate' and s['timestamp_offset_ns']=='344903'
assert s['mode']=='2' and s['running']=='1' and s['locked_mask']=='3' and s['error']=='0' and s['skipped']=='0'
assert 'ActiveState=active' in Path('exposure-start-final-service.txt').read_text()
assert 'NRestarts=0' in Path('exposure-start-final-service.txt').read_text()
assert Path('/var/lib/sc132gs-camera/settings.yaml').read_bytes()==Path('exposure-start-baseline-20261015/settings.yaml').read_bytes()
log=Path('exposure-start-final-server.log').read_text();dmesg=Path('exposure-start-final-dmesg.txt').read_text()
assert not re.search(r'queue overran|queue overflow|backlog exceeded|capture error|capture frame gap',log,re.I)
assert not re.search(r'Unhandled context fault|SOFTWARE TABLE WALK FAILED|fsr=0x402|Oops:|kernel BUG',dmesg,re.I)
metrics=re.findall(r'input_fps=([0-9.]+) submitted_fps=([0-9.]+) dropped_fps=([0-9.]+).*?pairs=(\d+)',log)
assert metrics and all(float(m[2])==0 for m in metrics)
Path('exposure-start-final-state-result.json').write_text(json.dumps({'passed':True,'abi':4,'source':s['source'],'timestamp_offset_ns':int(s['timestamp_offset_ns']),'session':int(s['session']),'smmu_or_oops_errors':0,'queue_errors':0,'server_dropped_fps':0,'last_pairs':int(metrics[-1][3]),'service_restarts':0},indent=2)+'\n')
PY
