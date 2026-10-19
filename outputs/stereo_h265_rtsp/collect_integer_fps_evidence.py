"""Bundle real transaction/decoder evidence, excluding the copied kernel module."""
import json
from pathlib import Path
import shutil
import zipfile
import camera_platform as platform

root=Path('/home/ubuntu/sc132gs-camera-tests/integer-fps-20261007')
latest=max(root.parent.glob('apply-*'),key=lambda path:path.stat().st_mtime)
shutil.copytree(latest,root/'final60-transaction',dirs_exist_ok=True)
for failure in sorted(root.parent.glob('failure-*'),key=lambda path:path.stat().st_mtime)[-2:]:
    shutil.copytree(failure,root/failure.name,dirs_exist_ok=True)
(root/'final-server.log').write_text(Path('/run/sc132gs-camera-server.log').read_text())
groups={}
for path in sorted(root.glob('*-transactions.json')):
    records=json.loads(path.read_text())
    latest={record['label']:record for record in records}
    groups[path.stem]=[dict(label=record['label'],returncode=record['returncode'],
        stdout=record['stdout'],stderr=record['stderr'],state=record['after'])
        for record in latest.values()]
summary=dict(groups=groups,final_state=platform.inspect(),durable=platform.durable_record())
(root/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
archive=root.with_suffix('.zip')
with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as bundle:
    for path in sorted(root.rglob('*')):
        if path.is_file() and path.suffix in ('.json','.png','.asm','.log'):
            bundle.write(path,path.relative_to(root))
print(json.dumps(dict(archive=str(archive),bytes=archive.stat().st_size,
    final_state=summary['final_state']),indent=2))
