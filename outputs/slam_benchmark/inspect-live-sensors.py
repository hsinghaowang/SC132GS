"""Read-only live endpoint and calibration discovery, not a timing proof."""
import json
import os
from pathlib import Path
import subprocess

def run(args):
    result=subprocess.run(args,capture_output=True,text=True,timeout=20)
    return dict(returncode=result.returncode,stdout=result.stdout,stderr=result.stderr)
adapters=[]
for entry in Path('/sys/class/i2c-adapter').glob('i2c-*'):
    adapters.append(dict(device='/dev/'+entry.name,name=(entry/'name').read_text().strip()))
gpio=[]
for entry in Path('/sys/bus/gpio/devices').glob('gpiochip*'):
    if (entry/'label').exists():gpio.append(dict(device='/dev/'+entry.name,label=(entry/'label').read_text().strip()))
files=[]
for directory in ('/home/ubuntu/gs130wi-imu','/home/ubuntu/stereo-h265-rtsp','/home/ubuntu/sc132gs-v4l2-probe','/home/ubuntu/calibration'):
    for current,subdirs,names in os.walk(directory):
        subdirs[:]=[name for name in subdirs if name not in ('build','.git','node_modules')]
        for name in names:
            if name.endswith(('.yaml','.yml','.json')) and any(word in name.lower() for word in ('calib','chain','camera','intrinsic')):
                files.append(str(Path(current)/name))
print(json.dumps(dict(i2c_adapters=adapters,gpio_chips=gpio,video_nodes=sorted(str(p) for p in Path('/dev').glob('video*')),
    candidate_calibration_files=files,
    imu_binary=run(['/home/ubuntu/gs130wi-imu/build/gs130wi-imu','--help']),
    camera_binaries=run(['ls','-l','/home/ubuntu/stereo-h265-rtsp/build/optical-raw-capture']),
    camera0_format=run(['v4l2-ctl','-d','/dev/video0','--get-fmt-video']),
    camera1_format=run(['v4l2-ctl','-d','/dev/video3','--get-fmt-video'])),indent=2))
