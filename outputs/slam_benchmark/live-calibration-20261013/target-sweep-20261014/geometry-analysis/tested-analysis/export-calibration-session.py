"""Export images for camera calibration; never fabricate common IMU time."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import cv2
import numpy as np

base=Path('/ws/slam_benchmark')
parser=argparse.ArgumentParser();parser.add_argument('session');args=parser.parse_args()
root=base/'live-calibration-20261013'/args.session
output=root/'prepared';output.mkdir(exist_ok=False)
def read(path):
    with path.open() as file:return list(csv.DictReader(file))
frames=read(root/'camera-frames.csv');pairs={}
for frame in frames:
    pair=pairs.setdefault(int(frame['pair_id']),{})
    eye=int(frame['eye']);assert eye not in pair
    pair[eye]=frame
assert pairs and all(set(pair)=={0,1} for pair in pairs.values())
image_stats=[];deltas=[];hashes={}
for eye in (0,1):(output/'images-only'/f'cam{eye}').mkdir(parents=True)
for pair_id,pair in sorted(pairs.items()):
    delta=abs(int(pair[0]['receiver_timestamp_ns'])-int(pair[1]['receiver_timestamp_ns']))
    assert delta<=3_000_000;deltas.append(delta/1e6)
    for eye,frame in pair.items():
        image=cv2.imread(str(root/frame['image']),cv2.IMREAD_GRAYSCALE)
        assert image is not None and image.shape==(1280,1088) and image.dtype==np.uint8
        name=f'images-only/cam{eye}/{frame["receiver_timestamp_ns"]}.png'
        assert not (output/name).exists()
        assert cv2.imwrite(str(output/name),image)
        decoded=cv2.imread(str(output/name),cv2.IMREAD_GRAYSCALE)
        assert np.array_equal(image,decoded)
        hashes[name]=hashlib.sha256((output/name).read_bytes()).hexdigest()
        if pair_id==min(pairs):
            assert cv2.imwrite(str(output/f'preview-eye{eye}.png'),image)
            image_stats.append(dict(eye=eye,mean=float(image.mean()),p01=float(np.percentile(image,1)),
                                    p99=float(np.percentile(image,99)),saturated_fraction=float(np.mean(image==255))))
raw=read(root/'imu-raw.csv');summary=json.loads((root/'imu-summary.json').read_text())
assert len(raw)==summary['samples']==summary['valid'] and summary['status']=='ok' and summary['restored']
sensor_times=np.array([int(row['sensor_elapsed_ns']) for row in raw],dtype=np.int64)
assert np.all(np.diff(sensor_times)>0)
with (output/'imu-si-relative.csv').open('w',newline='') as file:
    writer=csv.writer(file)
    writer.writerow(['sensor_elapsed_ns','omega_x_rad_s','omega_y_rad_s','omega_z_rad_s',
                     'alpha_x_m_s2','alpha_y_m_s2','alpha_z_m_s2','host_interrupt_ns','host_read_begin_ns','host_read_end_ns'])
    for row in raw:
        values=[float(row[key])*math.pi/180 for key in ('gx_dps','gy_dps','gz_dps')]+[float(row[key])*9.80665 for key in ('ax_g','ay_g','az_g')]
        assert all(map(math.isfinite,values))
        writer.writerow([row['sensor_elapsed_ns'],*values,row['host_interrupt_ns'],row['host_read_begin_ns'],row['host_read_end_ns']])
target=cv2.imread(str(base/'calibration-capture/checkerboard-detector-test.png'),cv2.IMREAD_GRAYSCALE)
found,corners=cv2.findChessboardCorners(target,(9,6))
assert found and len(corners)==54
pdf_image=cv2.imread(str(base/'calibration-capture/checkerboard-pdf-render.png'),cv2.IMREAD_GRAYSCALE)
pdf_found,pdf_corners=cv2.findChessboardCorners(pdf_image,(9,6))
assert pdf_found and len(pdf_corners)==54
units=read(output/'imu-si-relative.csv')
assert len(units)==len(raw)
for converted,source in zip(units,raw):
    for destination,key,scale in (
        ('omega_x_rad_s','gx_dps',math.pi/180),('omega_y_rad_s','gy_dps',math.pi/180),('omega_z_rad_s','gz_dps',math.pi/180),
        ('alpha_x_m_s2','ax_g',9.80665),('alpha_y_m_s2','ay_g',9.80665),('alpha_z_m_s2','az_g',9.80665)):
        assert math.isclose(float(converted[destination]),float(source[key])*scale,rel_tol=1e-12,abs_tol=1e-12)
coverage_path=root/'target-coverage/report.json'
target_coverage=json.loads(coverage_path.read_text()) if coverage_path.exists() else None
result=dict(status='target_capture_exported_imu_time_pending' if target_coverage else 'camera_capture_prepared_imu_time_pending',stereo_pairs=len(pairs),images_written=len(hashes),
    paired_driver_stamp_delta_ms=dict(p50=float(np.percentile(deltas,50)),p95=float(np.percentile(deltas,95)),max=float(max(deltas))),
    imu_samples=len(raw),png_pixel_roundtrip_passed=True,SI_unit_conversion_all_rows_passed=True,
    target_detector=dict(ideal_png=True,rendered_pdf=True,internal_corners=54),preview_metrics=image_stats,
    camera_driver_sequence_gaps=json.loads((root/'camera-summary.json').read_text())['driver_sequence_gaps'],
    saved_state_preserved=json.loads((root/'transaction.json').read_text())['saved_state_preserved'],
    imu_time_validated=False,camera_imu_bag_export_allowed=False,geometric_calibration_solved=False,
    observed_physical_target_coverage=({key:target_coverage[key] for key in ('sampled_pairs','stereo_target_pairs')} if target_coverage else None),
    limitations=['Physical target presence checked on a sampled subset; see target-coverage/report.json.' if target_coverage else 'No target was moved for this acquisition smoke test.',
                 'Paired driver timestamps do not establish equal exposure times.',
                 'IMU sensor-relative time is not a common host time; no imu0.csv placed in images-only.',
                 'Intrinsic/stereo and camera-IMU calibration still need physical target data and clock/noise work.'])
(output/'export-audit.json').write_text(json.dumps(result,indent=2))
(output/'images-sha256.json').write_text(json.dumps(hashes,indent=2))
print(json.dumps(result,indent=2))
