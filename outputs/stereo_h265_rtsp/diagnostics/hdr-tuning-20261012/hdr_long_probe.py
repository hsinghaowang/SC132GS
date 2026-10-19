"""Reversible HDR 20-FPS long-exposure probe before expanding driver controls."""
import json
from pathlib import Path
import subprocess
import sys
import time
import yaml
sys.path.insert(0,'/home/ubuntu/stereo-h265-rtsp')
import camera_platform as platform
from compare_modes import capture, OUT

saved=yaml.safe_load(platform.DURABLE.read_text())
records=[]

def set_tuple(rows):
    if not 8<=rows<=3629: raise ValueError('Probe exposure bound')
    for client in platform.CLIENTS:
        bus,address=client.split('-')
        def write(register,values):
            platform.run(['i2ctransfer','-f','-y',bus,
                'w'+str(2+len(values))+'@0x'+address,hex(register>>8),hex(register&255),
                *(hex(value) for value in values)])
        # Mirror the driver's group transaction; cached V4L2 TOTAL deliberately
        # remains 1492. AE is off, and the hardware tuple is read independently.
        total=rows*16
        write(0x3800,[0])
        write(0x3e00,[(total>>16)&15,(total>>8)&255,total&255])
        write(0x3e31,[0,1])
        write(0x5400,[255])
        write(0x3800,[0x10])
        write(0x3800,[0x60])

def read_tuple():
    result={}
    for client in platform.CLIENTS:
        bus,address=client.split('-')
        result[client]={name:platform.run(['i2ctransfer','-f','-y',bus,'w2@0x'+address,
            hex(register>>8),hex(register&255),'r'+str(count)])
            for name,register,count in [('total',0x3e00,3),('second',0x3e31,2),('ratio',0x5400,1)]}
    return result

try:
    subprocess.run(['sc132gs-camera','apply','--mode','hdr','--max-fps','20','--ae','off',
                    '--hdr-total-rows','1492','--gain-index','0'],check=True,timeout=50)
    for rows in (1492,2492,2992,3492,3629,1492):
        set_tuple(rows)
        time.sleep(2)
        name=f'hdr20-total{rows}-{len(records)}'
        result=dict(rows=rows,requested_fps=20,hardware_tuple=read_tuple(),
                    status=platform.request('status'),decoded=capture(name))
        records.append(result)
        (OUT/'long-exposure.json').write_text(json.dumps(records,indent=2))
        print(json.dumps(result),flush=True)
finally:
    if platform.active(platform.UNIT): set_tuple(1492)
    subprocess.run(['sc132gs-camera','apply','--mode',saved['mode'],'--max-fps',str(saved['max_fps']),
        '--ae','on' if saved['ae'] else 'off','--ae-target',str(saved['brightness']),
        '--max-gain-index',str(saved['max_gain_index']),'--max-exposure-us',str(saved['max_exposure_us'])],
        check=True,timeout=50)
