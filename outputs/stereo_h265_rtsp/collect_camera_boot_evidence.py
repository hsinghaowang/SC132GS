#!/usr/bin/env python3
import json
import argparse
from pathlib import Path
import subprocess
import camera_platform as adapter

def run(*args):
    result=subprocess.run(args,capture_output=True,text=True,timeout=15)
    return dict(returncode=result.returncode,stdout=result.stdout.strip(),stderr=result.stderr.strip())

parser=argparse.ArgumentParser()
parser.add_argument('--output',type=Path,default=Path('/home/ubuntu/sc132gs-camera-tests/reboot-persistence-20261007'))
parser.add_argument('--before-boot-id',default='32ea68cf-e469-46fe-a61a-f45559636ac3')
args=parser.parse_args()
root=args.output
root.mkdir(parents=True,exist_ok=True)
state=adapter.inspect()
durable=adapter.durable_record()
runtime=json.loads(adapter.STATE.read_text())
assert durable==runtime
for saved,actual in (('mode','sensor_mode'),('binning','binning'),('max_fps','max_fps'),
    ('fps','fps'),('ae','ae'),('brightness','brightness'),('max_exposure_us','max_exposure_us'),
    ('max_gain_index','max_gain_index'),('revision','revision')):
    assert durable[saved]==state[actual],(saved,durable,state)
record=dict(before_boot_id=args.before_boot_id,
    after_boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
    state=state,durable=durable,runtime=runtime,
    loaded_srcversion=Path('/sys/module/sc132gs/srcversion').read_text().strip(),
    disk_srcversion=run('modinfo','-F','srcversion','sc132gs'),
    boot_service=run('systemctl','status','sc132gs-camera-restore.service','--no-pager'),
    boot_enabled=run('systemctl','is-enabled','sc132gs-camera-restore.service'),
    kernel_errors=run('journalctl','-k','-b','-p','err','--no-pager'))
assert record['before_boot_id']!=record['after_boot_id']
assert record['loaded_srcversion']=='C64E79680C45EF0FB084F9D'
assert record['boot_service']['returncode']==0
(root/'boot.json').write_text(json.dumps(record,indent=2))
print(json.dumps(record,indent=2))
