import datetime
import json
from pathlib import Path
import subprocess
import time
from zoneinfo import ZoneInfo

root = Path('/home/ubuntu/capture-api-20261015')
samples = []
passed = True
started = time.monotonic()
for index in range(13):
    status = Path('/sys/bus/platform/devices/acb3000.camss/fsync_control').read_text().strip()
    fields = dict(token.split('=', 1) for token in status.split())
    service = subprocess.run(['systemctl', 'is-active', 'sc132gs-camera-rtsp.service'],
                             capture_output=True, text=True).stdout.strip()
    good = service == 'active' and fields['running'] == '1' and fields['error'] == '0' and fields['locked_mask'] == '3'
    samples.append({'time': datetime.datetime.now(ZoneInfo('Asia/Taipei')).isoformat(),
                    'elapsed_s': time.monotonic() - started, 'service': service, 'status': fields})
    if not good:
        passed = False
        break
    if index < 12:
        time.sleep(5)
report = {'passed': passed, 'samples': samples, 'scope': 'bounded 60-second original-service monitor, no long-run reliability claim'}
(root / 'restored-monitor.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'passed': passed, 'duration_s': samples[-1]['elapsed_s'], 'samples': len(samples)}))
raise SystemExit(0 if passed else 1)
