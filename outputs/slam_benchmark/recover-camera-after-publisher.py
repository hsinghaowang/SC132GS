"""After timed replay only: recover the previously authorized camera configuration."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

base=Path('/home/ubuntu/ros2_humble_ws/slam_benchmark/ros-results/publisher-comparison-20261013')
done=json.loads((base/'result.json').read_text())
assert done['returncode']==0 and done['original_camera_off_state_preserved']
root=base/'camera-recovery';root.mkdir(exist_ok=False)
settings=Path('/var/lib/sc132gs-camera/settings.yaml')
platform=Path('/home/ubuntu/stereo-h265-rtsp/camera_platform.py')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
before=sha(settings)
shutil.copyfile(settings,root/'settings-before.yaml')
shutil.copyfile('/run/sc132gs-camera-server.log',root/'server-failure-before.log')
start=time.time_ns()
result=subprocess.run(['python3',str(platform),'restore'],capture_output=True,text=True,timeout=100)
finish=time.time_ns()
(root/'restore.txt').write_text(result.stdout+result.stderr)
record=dict(start_unix_ns=start,finish_unix_ns=finish,returncode=result.returncode,
            durable_sha256_before=before,durable_sha256_after=sha(settings),platform_sha256=sha(platform))
if result.returncode==0:
    candidates=[p for p in Path('/home/ubuntu/sc132gs-camera-tests').glob('apply-*')
                if (p/'decode.json').exists() and start<=(p/'decode.json').stat().st_mtime_ns<=finish]
    assert candidates,'restore returned success without decoded proof'
    proof=max(candidates,key=lambda p:(p/'decode.json').stat().st_mtime_ns)
    for name in ('encoded.json','decode.json','decoded.png','request.json'):
        shutil.copyfile(proof/name,root/name)
    record['verification_source']=str(proof)
status=subprocess.run(['/usr/local/bin/sc132gs-camera','status'],capture_output=True,text=True,timeout=10)
(root/'status-after.txt').write_text(status.stdout+status.stderr)
record['status_returncode']=status.returncode
active=subprocess.run(['systemctl','is-active','sc132gs-camera-rtsp'],capture_output=True,text=True,timeout=10)
record['service_state']=active.stdout.strip()
record['durable_unchanged']=before==sha(settings)
(root/'result.json').write_text(json.dumps(record,indent=2))
print(json.dumps(record,indent=2));print(result.stdout,result.stderr)
assert record['durable_unchanged']
raise SystemExit(result.returncode)
