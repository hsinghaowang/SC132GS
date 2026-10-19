"""Read-only capture of the user's Linear visual comparison and live controls."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0,'/home/ubuntu/stereo-h265-rtsp')
import camera_platform as platform

root=Path('/home/ubuntu/hdr-tuning-20261012')
report=dict(observed_at_utc=datetime.now(timezone.utc).isoformat(),
    human_observation='User switched to Linear and reported no visible haze in the scene.',
    camera_status=platform.run(['sc132gs-camera','status']),
    ae_status=platform.run(['sc132gs-ctl','status']),
    state=platform.inspect(),
    runtime=json.loads(platform.STATE.read_text()),
    register_readbacks=[])
if report['state']['sensor_mode']!='linear': raise RuntimeError('Live mode changed before recording')
for bus,addr in ((18,'0x32'),(16,'0x30')):
    values={}
    for name,reg,count in (('mode',0x3220,1),('trigger',0x3222,1),
            ('total',0x3e00,3),('gain',0x3e08,2),('vts',0x320e,2),('hts',0x320c,2)):
        values[name]=platform.run(['i2ctransfer','-f','-y',str(bus),
            'w2@'+addr,hex(reg>>8),hex(reg&255),'r'+str(count)])
    report['register_readbacks'].append(dict(bus=bus,address=addr,values=values))
path=root/'linear-user-visual-confirmation-20261012.json'
with path.open('x') as output: json.dump(report,output,indent=2); output.write('\n')
print(report['camera_status'])
print('Saved user observation and read-only controls:', path)
