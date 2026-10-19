import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parent
data_dir = root / 'factory-calibration-20261013'
revision = '12bde1f530533a11eba1803c1de525cee928c88b'

def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

values = read_json(data_dir / 'raw-intrinsics.json')
official = read_json(data_dir / 'official-parser-output.json')
assert official['probe_passed']
for camera, side in [('cam0', 'right'), ('cam1', 'left')]:
    assert official[side]['fisheye']
    for field in ['intrinsics', 'distortion_coeffs']:
        assert values['cameras'][camera][field] == official[side][field], (camera, field)

source_hashes = {}
for relative in ['types.hpp', 'base/i2c/i2c.hpp', 'devices/eeprom/eeprom.hpp',
                 'devices/eeprom/union_stereo_imu_fisheye_v1p2r0n4.cpp']:
    copied = data_dir / 'reference-source' / relative
    original = root / 'calibration-research/gs130_camera_sdk/core/src' / relative
    assert copied.read_bytes() == original.read_bytes()
    source_hashes[relative] = digest(copied)
values['official_CPP_parser_crosscheck_passed'] = True
values['official_CPP_parser_crosscheck_scope'] = 'Unmodified official layout parser; file-backed transport; all 16 intrinsic/distortion doubles exactly match Python decoding'
write_json(data_dir / 'raw-intrinsics.json', values)
verification = {
    'status': 'passed', 'official_revision': revision,
    'official_sources_unmodified': True, 'source_sha256': source_hashes,
    'hardware_access_during_crosscheck': False,
    'header_probe_passed': True, 'intrinsic_and_distortion_doubles_exactly_matching': 16,
    'geometric_accuracy_validated': False,
    'scope': 'C++17 original decoder against captured EEPROM, independent of Python unpack implementation',
}
write_json(data_dir / 'parser-verification.json', verification)

next_step = 'Validate factory fisheye intrinsics/stereo geometry with target images, then validate IMU-to-host clock mapping, noise model and camera-IMU extrinsics/time offset before live OpenVINS input.'
status = read_json(root / 'openvins-status.json')
status['factory_calibration'] = {
    'status': 'read_decoded_and_official_parser_crosschecked',
    'intrinsics': 'factory-calibration-20261013/raw-intrinsics.yaml',
    'evidence': 'factory-calibration-20261013/raw-intrinsics.json',
    'actual_module_EEPROM_read': True, 'vendor': 'UNION', 'version': '1.2',
    'header_checksum_passed': True, 'repeat_reads_identical': True,
    'official_CPP_parser_crosscheck_passed': True,
    'camera_model': 'pinhole', 'distortion_model': 'equidistant',
    'resolution': [1088, 1280], 'geometric_validation_performed': False,
    'camera_IMU_time_synchronization_validated': False,
    'saved_camera_state_unchanged': True,
}
status['next_step'] = next_step
prep = status['physical_calibration_preparation']
prep['status'] = 'acquisition_prepared_factory_intrinsics_obtained_geometry_validation_pending'
prep['factory_intrinsics_obtained'] = True
prep['next_step'] = next_step
prep['remaining'][0] = 'Target images to validate factory fisheye intrinsics/stereo geometry; recalibrate if residuals require it'
write_json(root / 'openvins-status.json', status)

research_path = root / 'calibration-research/findings.json'
research = read_json(research_path)
research['status'] = 'official_source_found_and_actual_module_factory_intrinsics_obtained'
research['followup_actual_RUBIK_module_EEPROM_read'] = True
research['actual_module_calibration_values_obtained'] = True
research['factory_intrinsics_export'] = '../factory-calibration-20261013/raw-intrinsics.yaml'
research['next_step'] = next_step
write_json(research_path, research)

guide_path = root / 'calibration-capture/採集說明.md'
guide = guide_path.read_text(encoding='utf-8-sig')
old = '目前完成實體採集與資料格式驗證，還沒有相機標定結果。此階段先做相機內參／畸變和雙目外參；相機–IMU 外參需另補共同時間與 IMU 雜訊模型。'
new = '已完成實體採集與格式驗證，並從這顆模組 EEPROM 讀出 UNION V1.2 出廠內參。參見 [原始影像內參](../factory-calibration-20261013/raw-intrinsics.yaml)：未旋轉的 1088×1280，pinhole + equidistant 魚眼模型，cam0 為右眼、cam1 為左眼。兩次讀取一致，官方原始解析器已交叉核對全部內參／畸變數值。下一步先用標定板影像驗證出廠幾何精度；是否重標定由殘差決定。相機–IMU 外參仍需核對方向、單位、共同時間與 IMU 雜訊模型，不能直接視為 live VIO 已完成。'
if old in guide:
    guide = guide.replace(old, new, 1)
guide_path.write_text(guide, encoding='utf-8')

(data_dir / '讀取結果.md').write_text('''# 本模組出廠內參

已從 RUBIK Pi 3 上實際 GS130WI/SC132GS 模組讀取 EEPROM（bus18、0x50），格式為 UNION stereo-IMU fisheye V1.2 rotate0/n4。兩次 537-byte 讀取逐位元組一致，識別碼與標頭校驗碼通過；使用官方未修改的 C++17 解析器離線重讀，16 個內參／畸變 double 數值與匯出完全一致。

`raw-intrinsics.yaml` 是未旋轉、未校正的 1088×1280 原始影像內參，畸變為 equidistant，係數順序 k1/k2/k3/k4。cam0=右眼（0x32），cam1=左眼（0x30）。若影像縮放、裁切或旋轉，必須先調整內參；不能直接用在 RTSP 顯示畫面。

這是內參匯出，並非完整 OpenVINS/Kalibr 相機–IMU 配置。雙目外參在 JSON 保留原始值，平移單位尚未獨立驗證，未輸出 live VIO 外參。標頭校驗碼只覆蓋識別區，讀取一致與解析器吻合也不等於已驗證重投影精度。

`bus18-eeprom.bin`、`bus18-repeat.bin` 保留原始資料；`repeat-verification.json` 記錄兩次一致與相機前後狀態；`parser-verification.json` 記錄官方原始解析器比對及來源雜湊。讀取只改 EEPROM 位址指標，沒有寫入 EEPROM 內容。相機持久設定、runtime state 與原本停止的串流狀態保持不變。

下一步以標定板影像檢查兩眼全視野重投影與雙目幾何，再處理相機–IMU 外參、時間同步及 IMU 雜訊模型。
''', encoding='utf-8')

hashes = {str(path.relative_to(data_dir)).replace('\\', '/'): digest(path)
          for path in sorted(data_dir.rglob('*')) if path.is_file() and path.name != 'evidence-sha256.json'}
write_json(data_dir / 'evidence-sha256.json', hashes)
print(json.dumps({'official_parser_exact_values': 16, 'evidence_files': len(hashes),
                  'intrinsics_yaml': str(data_dir / 'raw-intrinsics.yaml')}, ensure_ascii=False))
