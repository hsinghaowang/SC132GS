"""Read known GS130 EEPROM headers via short CCI-compatible transactions.

I2C writes contain only the two-byte address pointer, followed immediately by a
read. No EEPROM data write, sensor register access or settings mutation occurs.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import time

base=Path('/home/ubuntu/ros2_humble_ws/slam_benchmark')
root=base/'factory-calibration-20261013';root.mkdir(exist_ok=False)
def snapshot():
    return json.loads(subprocess.check_output(['python3',str(base/'inspect-delivery-board.py')],text=True))
before=snapshot();(root/'before.json').write_text(json.dumps(before,indent=2))
assert 'ActiveState=inactive' in before['service']['stdout']
assert not any(p['comm'].startswith(('stereo-h265','sc132gs-fsync','native_replay','ros_replay')) for p in before['processes'])
records=[]
def read(bus,offset,count):
    result=subprocess.run(['i2ctransfer','-y',str(bus),'w2@0x50',hex(offset>>8),hex(offset&255),'r'+str(count)],capture_output=True,text=True,timeout=5)
    records.append(dict(bus=bus,address='0x50',offset=offset,read_bytes=count,returncode=result.returncode,stdout=result.stdout,stderr=result.stderr))
    if result.returncode:return None
    raw=bytes(int(word,16) for word in result.stdout.split())
    assert len(raw)==count
    return raw
result=dict(address='0x50',buses=[],EEPROM_memory_writes=0,
    protocol='Two-byte pointer then <=8-byte combined read, per official GS130 EEPROM layouts; no force option',
    decoder_source_revision='12bde1f530533a11eba1803c1de525cee928c88b')
known={b'UNION\0\0\0'+bytes((0x11,1,1,2,0,4,0)):('UNION_stereo_imu_fisheye_v1p2r0n4',0x219),
       b'SZYGSJKJ'+bytes((0x11,1,1,2,0,4,0)):('SZYGSJKJ_stereo_imu_fisheye_v1p2r0n4',0x2d9),
       b'SZYGSJKJ'+bytes((1,0,1,1,1,8,0)):('SZYGSJKJ_stereo_pinhole_v1p1r1n8',0xc0)}
try:
    for bus in (18,16):
        header0=read(bus,0,8)
        item=dict(bus=bus,readable=header0 is not None)
        if header0 is not None:
            header1=read(bus,8,8)
            if header1 is not None:
                header=header0+header1;(root/f'bus{bus}-header.bin').write_bytes(header)
                item.update(header_hex=header.hex(),header_checksum_valid=(sum(header[:14])%255)+1==header[15],
                    vendor=header[:8].rstrip(b'\0').decode('ascii',errors='replace'))
                if item['header_checksum_valid'] and header[:15] in known:
                    model,size=known[header[:15]]
                    chunks=[read(bus,offset,min(8,size-offset)) for offset in range(0,size,8)]
                    assert all(chunk is not None for chunk in chunks), 'full read incomplete'
                    blob=b''.join(chunks)
                    assert blob[:16]==header
                    (root/f'bus{bus}-eeprom.bin').write_bytes(blob)
                    item.update(model=model,bytes=size,sha256=hashlib.sha256(blob).hexdigest())
        result['buses'].append(item)
finally:
    after=snapshot();(root/'after.json').write_text(json.dumps(after,indent=2))
    result['saved_camera_state_unchanged']=before['files']==after['files'] and before['service']==after['service']
    (root/'transactions.json').write_text(json.dumps(records,indent=2))
    (root/'probe.json').write_text(json.dumps(result,indent=2))
    assert result['saved_camera_state_unchanged']
print(json.dumps(result,indent=2),flush=True)
