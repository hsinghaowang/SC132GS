"""Collect the completed camera verification and hash new raw evidence only."""
import hashlib
import json
from pathlib import Path
import shutil

root=Path('/home/ubuntu/ros2_humble_ws/slam_benchmark/ros-results')
camera=root/'camera-pause-restore'
result=json.loads((camera/'result.json').read_text())
assert result['benchmark_returncode']==0 and result['restored'] and result['durable_unchanged']
restoration=json.loads((camera/'restore-camera.json').read_text())
start=restoration['started_unix_ns']
finish=restoration['finished_unix_ns']
candidates=[p for p in Path('/home/ubuntu/sc132gs-camera-tests').glob('apply-*')
            if (p/'decode.json').exists() and start<=(p/'decode.json').stat().st_mtime_ns<=finish]
assert candidates, 'No decoded restoration proof within recorded restoration interval'
proof=max(candidates,key=lambda p:(p/'decode.json').stat().st_mtime_ns)
for name in ('request.json','encoded.json','decode.json','decoded.png'):
    shutil.copyfile(proof/name,camera/('verification-'+name))
(camera/'verification-origin.json').write_text(json.dumps(dict(source_directory=str(proof),
    restore_start_unix_ns=start,restore_finish_unix_ns=finish),indent=2))
files=list(camera.rglob('*'))+[root/'exclusive-platform-load.jsonl']
dirs=list(root.glob('*-paced-exclusive-*'))
assert len(dirs)==6
for directory in dirs:
    assert (directory/'replay-summary.json').exists() and (directory/'receiver-summary.json').exists()
    files+=list(directory.rglob('*'))
hashes={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.is_file()}
(root/'exclusive-raw-sha256.json').write_text(json.dumps(hashes,indent=2))
print(json.dumps(dict(raw_files=len(hashes),verification_directory=str(proof),camera=result),indent=2))
