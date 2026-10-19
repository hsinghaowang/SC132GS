import hashlib
import json
from pathlib import Path
import subprocess

def run(args):
    result=subprocess.run(args,capture_output=True,text=True,timeout=15)
    return dict(returncode=result.returncode,stdout=result.stdout,stderr=result.stderr)

processes=[]
for entry in Path('/proc').glob('[0-9]*/comm'):
    try:
        comm=entry.read_text().strip()
        if comm.startswith(('stereo-h265','sc132gs-fsync','ros_replay','native_replay','python','cc1','ninja','make','ffmpeg')):
            processes.append(dict(pid=int(entry.parent.name),comm=comm,args=(entry.parent/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')))
    except OSError:pass
files={}
for path in ('/var/lib/sc132gs-camera/settings.yaml','/run/sc132gs-camera-state.json'):
    file=Path(path)
    if file.exists():files[path]=dict(sha256=hashlib.sha256(file.read_bytes()).hexdigest(),text=file.read_text())
print(json.dumps(dict(service=run(['systemctl','show','sc132gs-camera-rtsp','-p','ActiveState','-p','SubState','-p','MainPID','-p','Environment']),
                     camera_status=run(['/usr/local/bin/sc132gs-camera','status']),files=files,processes=processes,
                     containers=run(['docker','ps','--format','{{.Names}} {{.Status}}']),
                     versions=run(['docker','exec','ros2-humble','dpkg-query','-W','ros-humble-fastrtps','ros-humble-rmw-fastrtps-cpp'])),indent=2))
