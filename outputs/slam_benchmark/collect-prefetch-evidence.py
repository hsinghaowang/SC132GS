"""Hash completed decode-ahead evidence and preserve the failed camera recovery logs."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

base=Path('/home/ubuntu/ros2_humble_ws/slam_benchmark');root=base/'ros-results'
evidence=root/'prefetch-comparison-20261013'
done=json.loads((evidence/'result.json').read_text());assert done['returncode']==0
camera=root/'publisher-comparison-20261013/camera-recovery'
recovery=json.loads((camera/'result.json').read_text())
shutil.copyfile(evidence/'camera-failure-before.log',camera/'server-failure-after.log')
for p in Path('/home/ubuntu/sc132gs-camera-tests').glob('apply-*'):
    f=p/'encoded.json'
    if f.exists() and recovery['start_unix_ns']<=f.stat().st_mtime_ns<=recovery['finish_unix_ns']:
        shutil.copyfile(f,camera/'encoded-failure.json')
journal=subprocess.run(['journalctl','-k','--no-pager','--since','@'+str(recovery['start_unix_ns']//10**9),
    '--until','@'+str(recovery['finish_unix_ns']//10**9+2)],capture_output=True,text=True,timeout=10)
(camera/'kernel-recovery.txt').write_text(journal.stdout+journal.stderr)
files=list(evidence.rglob('*'))+list(camera.rglob('*'))
for dataset in ('MH_01_easy','V2_02_medium'):
    for repeat in (1,2):
        directory=root/f'{dataset}-paced-prefetch-{repeat}'
        assert (directory/'replay-summary.json').exists()
        files+=list(directory.rglob('*'))
for name in ('V2_02_medium-paced-prefetch-smoke','prefetch-payload-validation','prefetch-payload-validation-2','prefetch-active-stop'):
    files+=list((root/name).rglob('*'))
hashes={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
    for p in files if p.is_file() and p.name!='raw-sha256.json'}
(evidence/'raw-sha256.json').write_text(json.dumps(hashes,indent=2))
print(json.dumps(dict(raw_files=len(hashes),done=done),indent=2))
