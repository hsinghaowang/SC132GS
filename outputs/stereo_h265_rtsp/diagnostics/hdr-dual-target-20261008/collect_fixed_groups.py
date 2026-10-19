import json,subprocess,time
from pathlib import Path
records=[]
for _ in range(20):
    reply=subprocess.check_output(['sudo','sc132gs-ctl','status'],text=True).strip()
    record=dict(item.split('=',1) for item in reply.split()[1:])
    records.append({'monotonic':time.monotonic(),'status':record})
    time.sleep(1)
Path('/home/ubuntu/hdr-dual-target-20261008/fixed-groups-convergence.json').write_text(json.dumps(records,indent=2))
print(json.dumps(records[-1],indent=2))
