import hashlib
import json
from pathlib import Path
import shutil
import subprocess

base = Path('/home/ubuntu/ros2_humble_ws/slam_benchmark')
ready = base / 'calibration-ready-20261014'
session = base / 'live-calibration-20261013/target-sweep-20261014'
assert json.loads((session / 'prepared/export-audit.json').read_text())['png_pixel_roundtrip_passed']
sources = session / 'geometry-analysis/tested-analysis'
sources.mkdir(exist_ok=False)
for name in ['inspect-target-session.py', 'analyze-target-calibration.py', 'export-stereo-candidate.py',
             'export-calibration-session.py', 'collect-target-evidence.py']:
    shutil.copyfile(base / name, sources / name)
shutil.copyfile(base / 'factory-calibration-20261013/raw-intrinsics.json', sources / 'factory-intrinsics-input.json')
metrology = dict(date='2026-10-14', timezone='Asia/Taipei', source='direct_user_reply_in_this_chat',
    user_statement='已確認 20 mm，且平整固定', square_size_m_reported=.020,
    horizontal_and_vertical_square_spacing_user_confirmed=True, flat_mount_user_confirmed=True,
    independently_measured_by_agent=False)
(session / 'geometry-analysis/target-metrology.json').write_text(json.dumps(metrology, ensure_ascii=False, indent=2) + '\n')
shutil.copyfile(ready / 'rtsp-decode/decoded.png', ready / 'initial-six-frame-decoder-diagnostic.png')
after = subprocess.run(['python3', str(base / 'inspect-delivery-board.py')], capture_output=True, text=True, check=True)
after = json.loads(after.stdout)
(ready / 'after.json').write_text(json.dumps(after, indent=2))
before = json.loads((ready / 'before.json').read_text())
assert before['files'] == after['files']
assert 'ActiveState=active' in after['service']['stdout']
assert 'SubState=running' in after['service']['stdout']
(ready / 'final-state.json').write_text(json.dumps(dict(
    saved_camera_settings_unchanged=True, final_stream_state='active_at_explicit_user_request',
    initial_service_state='failed_unowned', failure_logs_saved=True,
    short_capture_and_90s_capture_driver_controls_restored=True,
    EEPROM_writes=0, calibrated_candidate_deployed=False), indent=2) + '\n')
hashes = {}
for path in sorted(session.rglob('*')):
    if path.is_file() and path.name != 'session-sha256.json':
        hashes[str(path.relative_to(session))] = hashlib.sha256(path.read_bytes()).hexdigest()
(session / 'session-sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
archive = base / 'calibration-target-20261014-evidence.tar'
assert not archive.exists()
# Every saved camera image is backed up as a verified pixel-identical lossless PNG.
# Original PGM files and their hashes remain on the board; no sensor-time rewriting.
subprocess.run(['tar', '-C', str(base),
    '--exclude=live-calibration-20261013/target-sweep-20261014/cam0',
    '--exclude=live-calibration-20261013/target-sweep-20261014/cam1',
    '-cf', str(archive), 'live-calibration-20261013/target-sweep-20261014', 'calibration-ready-20261014'], check=True)
print(json.dumps(dict(session_files_hashed=len(hashes), archive_bytes=archive.stat().st_size,
    archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
    backup_scope='All 898 saved images in pixel-identical PNG, raw PGM hashes retained; originals remain on board',
    rtsp_active=True, settings_unchanged=True)), flush=True)
