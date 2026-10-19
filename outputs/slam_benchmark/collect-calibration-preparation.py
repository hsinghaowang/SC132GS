import hashlib
import json
from pathlib import Path
import subprocess
import tarfile

base=Path('/home/ubuntu/ros2_humble_ws/slam_benchmark')
root=base/'live-calibration-20261013'
audit=json.loads((root/'paired-10s/prepared/export-audit.json').read_text())
assert audit['stereo_pairs']==50 and audit['png_pixel_roundtrip_passed'] and audit['SI_unit_conversion_all_rows_passed']
assert audit['saved_state_preserved'] and not audit['camera_imu_bag_export_allowed']
inspection=subprocess.check_output(['python3',str(base/'inspect-delivery-board.py')],text=True)
(root/'board-final.json').write_text(inspection)
last=json.loads(inspection);first=json.loads((root/'board-before.json').read_text())
assert last['files']==first['files'] and last['service']==first['service']
selected=[path for path in root.rglob('*') if path.is_file() and path.name!='raw-sha256.json'
          and not ('smoke-10s' in path.parts and path.suffix=='.pgm')]
manifest={str(path.relative_to(root)):hashlib.sha256(path.read_bytes()).hexdigest() for path in selected}
(root/'raw-sha256.json').write_text(json.dumps(manifest,indent=2))
archive=base/'live-calibration-20261013.tar.gz'
with tarfile.open(archive,'w:gz',compresslevel=1) as tar:
    for path in selected+[root/'raw-sha256.json']:tar.add(path,arcname=str(path.relative_to(root)))
print(json.dumps(dict(files=len(manifest),bytes=archive.stat().st_size,sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),archive=str(archive))))
