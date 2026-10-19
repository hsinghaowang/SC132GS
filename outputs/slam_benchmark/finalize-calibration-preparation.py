import hashlib
import importlib.util
import json
from pathlib import Path

base=Path(__file__).resolve().parent
root=base/'live-calibration-20261013';paired=root/'paired-10s'
manifest=json.loads((root/'raw-sha256.json').read_text())
assert all(hashlib.sha256((root/name).read_bytes()).hexdigest()==digest for name,digest in manifest.items())
transaction=json.loads((paired/'transaction.json').read_text())
assert transaction['saved_state_preserved']
assert transaction['before']['files']==transaction['after']['files']
assert transaction['saved_driver_controls']==transaction['driver_controls_after']
assert 'ActiveState=inactive' in transaction['after']['service']['stdout']
for name,digest in transaction['source_sha256'].items():
    saved=paired/'tested-sources'/name
    assert hashlib.sha256(saved.read_bytes()).hexdigest()==digest,name
    if (base/name).exists():assert hashlib.sha256((base/name).read_bytes()).hexdigest()==digest,name
spec=importlib.util.spec_from_file_location('imu_audit',base/'audit_imu.py')
audit_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit_module)
imu=audit_module.audit(paired/'imu-raw.csv',paired/'imu-summary.json')
imu['evidence_type']='live_acquisition_capture_integrity'
assert imu['capture_integrity_passed'] and not imu['live_vio_time_ready']
(paired/'imu-integrity.json').write_text(json.dumps(imu,indent=2))
export=json.loads((paired/'prepared/export-audit.json').read_text())
assert export['stereo_pairs']==50 and export['target_detector']['rendered_pdf']
assert export['paired_driver_stamp_delta_ms']['max']<=3
assert export['png_pixel_roundtrip_passed'] and export['SI_unit_conversion_all_rows_passed']
pdf=base.parents[1]/'output/pdf/sc132gs-checkerboard-a4-20mm.pdf'
result=dict(date='2026-10-13',timezone='Asia/Taipei',status='acquisition_prepared_waiting_for_physical_target',
    physical_camera_imu_acquisition=True,physical_openvins_vio_performed=False,
    stereo_pairs=50,camera_resolution=[1088,1280],png_images=100,imu_samples=2628,
    paired_driver_timestamp_delta_ms=export['paired_driver_stamp_delta_ms'],
    driver_timestamp_not_exposure_proof=True,imu_host_sample_time_validated=False,
    camera_driver_sequence_gaps=export['camera_driver_sequence_gaps'],
    camera_saved_controls_and_inactive_state_preserved=True,
    capture_api='C++17 public API/PIMPL/move-only; C++23 private implementation; joined owned storage worker; nested optional Observer',
    cpp17_header_compile_check_passed=True,cpp23_board_build_passed=True,
    nominal_sensor_counter_rate_hz=imu['sensor_counter_rate_hz'],host_read_observed_rate_hz=imu['host_read_observed_rate_hz'],
    PDF=dict(path=str(pdf),sha256=hashlib.sha256(pdf.read_bytes()).hexdigest(),
             print_size='Landscape A4; 9x6 inner corners; 20mm squares; 50mm ruler',
             rendered_visual_inspection_passed=True,rendered_detector_corners=54),
    raw_files_verified=len(manifest),guide='calibration-capture/採集說明.md',
    camera_intrinsic_and_stereo_calibration_solved=False,camera_imu_calibration_solved=False,
    combined_camera_imu_bag_export_allowed=False,
    next_step='Print target at actual size, verify 20mm squares/50mm ruler, mount flat and capture varied stationary board poses in both cameras.',
    remaining=['Physical target data and geometric solution','Validated IMU sensor-to-host clock mapping and sample latency','IMU noise/bias random-walk model','Physical camera-IMU extrinsics/time offset and live VIO validation'])
(root/'status.json').write_text(json.dumps(result,indent=2,ensure_ascii=False))
status_path=base/'openvins-status.json';status=json.loads(status_path.read_text())
status['physical_calibration_preparation']=result
status['physical_sensor_acquisition_performed']=True
status['real_camera_imu_test_scope']='OpenVINS live physical integration still untested; physical sensor acquisition verified separately'
status['next_step']=result['next_step']+' Establish IMU common-time/noise model before combined calibration and OpenVINS live input.'
status_path.write_text(json.dumps(status,indent=2,ensure_ascii=False))
verification=dict(raw_files_verified=len(manifest),frozen_capture_source_hashes_passed=True,
    capture_integrity_passed=imu['capture_integrity_passed'],PNG_and_SI_verification_passed=True,
    pdf_verified=True,camera_restoration_verified=True,
    source_sha256={name:hashlib.sha256((base/name).read_bytes()).hexdigest() for name in (
        'capture-calibration-session.py','export-calibration-session.py','finalize-calibration-preparation.py',
        'calibration-capture/CalibrationCapture.hpp','calibration-capture/CalibrationCapture.cpp','calibration-capture/API17CompileCheck.cpp')})
(root/'verification.json').write_text(json.dumps(verification,indent=2))
print(json.dumps(dict(status=result['status'],raw_files_verified=len(manifest),stereo_pairs=50,
                     paired_driver_timestamp_delta_ms=result['paired_driver_timestamp_delta_ms'],
                     imu_capture_passed=imu['capture_integrity_passed'],physical_vio_performed=False),indent=2))
