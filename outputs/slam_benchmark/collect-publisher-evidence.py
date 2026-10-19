"""Hash only completed publisher-comparison evidence, never rewrite older results."""
import hashlib
import json
from pathlib import Path

base=Path('/home/ubuntu/ros2_humble_ws/slam_benchmark')
root=base/'ros-results'
evidence=root/'publisher-comparison-20261013'
result=json.loads((evidence/'result.json').read_text())
assert result['returncode']==0 and result['original_camera_off_state_preserved']
files=list(evidence.rglob('*'))
for dataset in ('MH_01_easy','V2_02_medium'):
    for variant,repeat in (('pubcontrol',1),('nativepub',1),('nativepub',2)):
        path=root/f'{dataset}-paced-{variant}-{repeat}'
        assert (path/'replay-summary.json').exists() and (path/'receiver-summary.json').exists()
        files+=list(path.rglob('*'))
for name in ('V2_02_medium-paced-nativepub-smoke','native-publisher-discovery-interrupt'):
    files+=list((root/name).rglob('*'))
hashes={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in files if p.is_file() and p.name!='raw-sha256.json'}
(evidence/'raw-sha256.json').write_text(json.dumps(hashes,indent=2))
print(json.dumps(dict(raw_files=len(hashes),result=result),indent=2))
