import hashlib
import json
from pathlib import Path
import shutil
import subprocess

base = Path('/home/ubuntu/ros2_humble_ws/slam_benchmark')
root = base / 'stereo-validation-20261014'
session = base / 'live-calibration-20261013/target-validation-20261014'
result = json.loads((root / 'evaluation/report.json').read_text())
audit = json.loads((session / 'prepared/export-audit.json').read_text())
transaction = json.loads((root / 'transaction.json').read_text())
assert result['candidate_unchanged'] and not result['parameter_optimization_or_refit_performed']
assert audit['png_pixel_roundtrip_passed'] and audit['SI_unit_conversion_all_rows_passed']
assert transaction['saved_settings_unchanged'] and transaction['rtsp_active_restored']
sources = root / 'tested-analysis'
sources.mkdir(exist_ok=False)
for name in ['evaluate-independent-stereo.py', 'inspect-target-session.py', 'export-calibration-session.py', 'collect-independent-stereo.py']:
    shutil.copyfile(base / name, sources / name)
shutil.copyfile(base / 'live-calibration-20261013/target-sweep-20261014/geometry-analysis/target-metrology.json',
                root / 'target-metrology-user-confirmed.json')
inventory = {str(path.relative_to(session)): hashlib.sha256(path.read_bytes()).hexdigest()
    for path in sorted(session.rglob('*')) if path.is_file() and path.name != 'session-sha256.json'}
(session / 'session-sha256.json').write_text(json.dumps(inventory, indent=2) + '\n')
after = subprocess.run(['python3', str(base / 'inspect-delivery-board.py')], capture_output=True, text=True, check=True)
(root / 'after-evaluation.json').write_text(after.stdout)
snapshot = json.loads(after.stdout)
assert 'ActiveState=active' in snapshot['service']['stdout']
assert snapshot['files'] == json.loads((root / 'before.json').read_text())['files']
archive = base / 'stereo-validation-20261014-evidence.tar'
assert not archive.exists()
subprocess.run(['tar', '-C', str(base),
    '--exclude=live-calibration-20261013/target-validation-20261014/cam0',
    '--exclude=live-calibration-20261013/target-validation-20261014/cam1',
    '-cf', str(archive), 'live-calibration-20261013/target-validation-20261014', 'stereo-validation-20261014'], check=True)
proof = dict(archive_bytes=archive.stat().st_size, archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
             session_files_hashed=len(inventory), png_images=audit['images_written'],
             original_PGM_retained_on_board=True, all_PNG_pixel_equal_to_original_PGM=True,
             candidate_frozen_and_unchanged=True, rtsp_active=True, saved_settings_unchanged=True)
(base / 'stereo-validation-20261014-archive.json').write_text(json.dumps(proof, indent=2) + '\n')
print(json.dumps(proof), flush=True)
