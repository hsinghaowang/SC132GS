"""Host-side gate and read-only load monitor for the unchanged ROS2 replay."""
import json
import subprocess
import sys
import time
from pathlib import Path

base=Path('/home/ubuntu/ros2_humble_ws/slam_benchmark')
camera=[]
for path in Path('/proc').glob('[0-9]*/comm'):
    try:
        name=path.read_text().strip()
        if name.startswith(('stereo-h265','sc132gs-fsync')):camera.append({'pid':int(path.parent.name),'comm':name})
    except OSError:pass
if camera:
    print(json.dumps({'status':'background_camera_still_running','processes':camera}),flush=True)
    sys.exit(2)
load=base/'ros-results/exclusive-platform-load.jsonl'
if load.exists():raise RuntimeError('existing exclusive load evidence; do not overwrite')
monitor=subprocess.Popen([sys.executable,str(base/'sample-board-load.py'),str(load)])
try:
    time.sleep(3)
    completed=subprocess.run(['sudo','-n','docker','exec','ros2-humble','bash','/ws/slam_benchmark/run-exclusive-replay.sh'])
finally:
    monitor.terminate();monitor.wait(timeout=5)
sys.exit(completed.returncode)
