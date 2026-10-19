"""Export an offline camera-only candidate; do not alter the running RTSP pipeline."""
import argparse
import csv
import json
from pathlib import Path

import cv2
import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument('session')
args = parser.parse_args()
base = Path('/ws/slam_benchmark')
root = base / 'live-calibration-20261013' / args.session
output = root / 'geometry-analysis'
report = json.loads((output / 'report.json').read_text())
calibration = json.loads((base / 'factory-calibration-20261013/raw-intrinsics.json').read_text())
candidate = report['candidate']
assert candidate['status'] == 'fixed_intrinsics_stereo_candidate_not_deployed'
R = np.array(candidate['R_cam1_cam0'])
T = np.array(candidate['T_cam1_cam0_m_assuming_20mm_squares'])
assert np.max(np.abs(R.T @ R - np.eye(3))) < 1e-9 and abs(np.linalg.det(R) - 1) < 1e-9
transform = np.eye(4)
transform[:3, :3] = R
transform[:3, 3] = T
text = ['# CAMERA-ONLY CANDIDATE; not deployed; not a complete OpenVINS/IMU config.',
        '# Unrotated RAW 1088x1280; cam0=RIGHT 0x32, cam1=LEFT 0x30.',
        '# Intrinsics and equidistant coefficients are unchanged factory EEPROM values.',
        '# Translation in meters is CONDITIONAL on actual flat 20mm square spacing.',
        '# T_cn_cnm1 maps cam0 points into cam1: p_cam1=R*p_cam0+T.',
        '# No T_cam_imu or common-time claim is supplied.',
        '# 9 diverse poses fitted, 4 representatives withheld; one session; limited field coverage.']
for eye in (0, 1):
    camera = calibration['cameras'][f'cam{eye}']
    text += [f'cam{eye}:', '  camera_model: pinhole', '  distortion_model: equidistant',
             '  intrinsics: ' + json.dumps(camera['intrinsics']),
             '  distortion_coeffs: ' + json.dumps(camera['distortion_coeffs']),
             '  resolution: [1088, 1280]', f'  rostopic: /cam{eye}/image_raw',
             '  cam_overlaps: [' + str(1-eye) + ']']
    if eye:
        text += ['  T_cn_cnm1:'] + ['  - ' + json.dumps(row.tolist()) for row in transform]
(output / 'stereo-candidate.yaml').write_text('\n'.join(text) + '\n')

K = [np.array(calibration['cameras'][f'cam{eye}']['K'], dtype=np.float64) for eye in (0, 1)]
D = [np.array(calibration['cameras'][f'cam{eye}']['distortion_coeffs'], dtype=np.float64) for eye in (0, 1)]
rows = list(csv.DictReader((root / 'camera-frames.csv').open()))
pairs = {}
for row in rows:
    pairs.setdefault(int(row['pair_id']), {})[int(row['eye'])] = row
pair_id = candidate['held_out_pair_ids'][0]
images = [cv2.imread(str(root / pairs[pair_id][eye]['image']), cv2.IMREAD_GRAYSCALE) for eye in (0, 1)]
factory_R = np.array(report['factory_stereo']['R_cam1_cam0'])
factory_T = np.array(report['factory_stereo']['T_cam1_cam0_raw_units'])
for name, rotation, translation in [('factory', factory_R, factory_T), ('candidate', R, T)]:
    r0, r1, p0, p1, _ = cv2.fisheye.stereoRectify(K[0], D[0], K[1], D[1], (1088, 1280), rotation, translation,
           flags=cv2.CALIB_ZERO_DISPARITY, newImageSize=(1088, 1280), balance=0.0)
    rectified = []
    for eye in (0, 1):
        maps = cv2.fisheye.initUndistortRectifyMap(K[eye], D[eye], [r0, r1][eye], [p0, p1][eye],
                                                 (1088, 1280), cv2.CV_32FC1)
        rectified.append(cv2.remap(images[eye], *maps, cv2.INTER_LINEAR))
    canvas = cv2.cvtColor(cv2.resize(np.hstack(rectified), None, fx=.5, fy=.5), cv2.COLOR_GRAY2BGR)
    for y in range(32, canvas.shape[0], 32):
        cv2.line(canvas, (0, y), (canvas.shape[1]-1, y), (0, 190, 255), 1)
    cv2.putText(canvas, f'{name}; held-out pair {pair_id}; cam0 RIGHT | cam1 LEFT', (12, 23),
                cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 255, 255), 1, cv2.LINE_AA)
    assert cv2.imwrite(str(output / f'{name}-preview.png'), canvas)
print(json.dumps(dict(camera_only_candidate_exported=True, intrinsics_unchanged=True,
                      live_camera_settings_modified=False, held_out_preview_pair=pair_id)))
