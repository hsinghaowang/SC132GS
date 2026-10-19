import hashlib
import json
from pathlib import Path
import subprocess

base=Path('/home/ubuntu/ros2_humble_ws/slam_benchmark')
root=base/'factory-calibration-20261013'
assert not (root/'bus18-repeat.bin').exists()
probe=json.loads((root/'probe.json').read_text())
hit=next(item for item in probe['buses'] if item.get('model')=='UNION_stereo_imu_fisheye_v1p2r0n4')
assert hit['bus']==18 and hit['bytes']==537
before=json.loads(subprocess.check_output(['python3',str(base/'inspect-delivery-board.py')],text=True))
assert 'ActiveState=inactive' in before['service']['stdout']
transactions=[];blob=bytearray()
try:
    for offset in range(0,537,8):
        count=min(8,537-offset)
        result=subprocess.run(['i2ctransfer','-y','18','w2@0x50',hex(offset>>8),hex(offset&255),'r'+str(count)],capture_output=True,text=True,timeout=5)
        transactions.append(dict(offset=offset,count=count,returncode=result.returncode,stdout=result.stdout,stderr=result.stderr))
        result.check_returncode()
        chunk=bytes(int(word,16) for word in result.stdout.split());assert len(chunk)==count
        blob.extend(chunk)
    (root/'bus18-repeat.bin').write_bytes(blob)
    assert bytes(blob)==(root/'bus18-eeprom.bin').read_bytes()
finally:
    after=json.loads(subprocess.check_output(['python3',str(base/'inspect-delivery-board.py')],text=True))
    unchanged=before['files']==after['files'] and before['service']==after['service']
    (root/'repeat-transactions.json').write_text(json.dumps(transactions,indent=2))
    (root/'repeat-verification.json').write_text(json.dumps(dict(identical=bytes(blob)==(root/'bus18-eeprom.bin').read_bytes(),
        bytes=len(blob),sha256=hashlib.sha256(blob).hexdigest(),saved_camera_state_unchanged=unchanged,
        EEPROM_memory_writes=0,after=after),indent=2))
    assert unchanged
print(json.dumps(dict(repeat_identical=True,bytes=len(blob),saved_state_unchanged=unchanged)),flush=True)
