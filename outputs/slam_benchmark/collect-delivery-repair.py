"""Collect completed experiment only, including device-state preservation."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

base=Path('/home/ubuntu/ros2_humble_ws/slam_benchmark')
root=base/'ros-results';evidence=root/'delivery-repair-20261013'
full=json.loads((evidence/'full-results.json').read_text())
assert len(full)==4 and all(not any(item['input_missing'].values()) for item in full)
gate=json.loads((evidence/'gate-validation.json').read_text())
assert [item['returncode'] for item in gate]==[4,0]
inspection=subprocess.run(['python3',str(base/'inspect-delivery-board.py')],capture_output=True,text=True,check=True)
(evidence/'final-board-inspection.json').write_text(inspection.stdout)
snapshot=json.loads(inspection.stdout)
assert 'ActiveState=inactive' in snapshot['service']['stdout']
assert not any(process['comm'].startswith(('stereo-h265','sc132gs-fsync','ros_replay','native_replay')) for process in snapshot['processes'])
before=json.loads((evidence/'before.json').read_text())
assert snapshot['files']['/var/lib/sc132gs-camera/settings.yaml']['sha256']==before['durable_sha256']
assert snapshot['files']['/run/sc132gs-camera-state.json']['sha256']==before['runtime_sha256']
for name in ('ros-replay-native-checked.py','validate-prefetch-payload-4m.py','validate-delivery-gate.py',
             'run-frame-ready-replay.sh','run-delivery-full-observed.py','inspect-delivery-board.py','collect-delivery-repair.py'):
    shutil.copyfile(base/name,evidence/'tested-sources'/name)
folders=[evidence]+sorted(root.glob('*-paced-delivery-*'))+[root/'delivery-shm4m-payload']
files=[path for folder in folders for path in folder.rglob('*') if path.is_file() and path.name!='raw-sha256.json']
manifest={str(path.relative_to(root)):hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
(evidence/'raw-sha256.json').write_text(json.dumps(manifest,indent=2))
archive=base/'delivery-repair-20261013.tar.gz'
with tarfile.open(archive,'w:gz',compresslevel=1) as tar:
    for folder in folders:tar.add(folder,arcname=folder.name)
print(json.dumps(dict(files=len(files),archive=str(archive),sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),bytes=archive.stat().st_size)))
