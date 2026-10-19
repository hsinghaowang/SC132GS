"""Evaluate frozen calibration on a second session. No parameter fitting or update."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument('--base', type=Path, default=Path('/ws/slam_benchmark'))
parser.add_argument('--root-name', default='stereo-validation-20261014')
parser.add_argument('--session', default='target-validation-20261014')
args = parser.parse_args()
base = args.base
root = base / args.root_name
session = base / 'live-calibration-20261013' / args.session
output = root / 'evaluation'
output.mkdir(exist_ok=False)
inspection = json.loads((session / 'target-coverage/report.json').read_text())
parameters_path = root / 'frozen-candidate.npz'
parameters_hash = hashlib.sha256(parameters_path.read_bytes()).hexdigest()
transaction = json.loads((root / 'transaction.json').read_text())
assert parameters_hash == transaction['frozen_candidate_sha256']
parameters = np.load(parameters_path)
K = [parameters[f'K{eye}'].copy() for eye in (0, 1)]
D = [parameters[f'D{eye}'].copy() for eye in (0, 1)]
candidate_R = parameters['R_cam1_cam0'].copy()
candidate_T = parameters['T_cam1_cam0_m_assuming_20mm_squares'].copy()
factory = json.loads((root / 'frozen-intrinsics.json').read_text())
for eye in (0, 1):
    assert np.array_equal(K[eye], np.array(factory['cameras'][f'cam{eye}']['K']))
    assert np.array_equal(D[eye], np.array(factory['cameras'][f'cam{eye}']['distortion_coeffs']))
factory_R = np.array(factory['stereo_factory_raw']['rotation_left_to_right']).T
factory_T = -factory_R @ np.array(factory['stereo_factory_raw']['translation_left_to_right'])
objects = np.zeros((54, 1, 3), dtype=np.float64)
objects[:, 0, :2] = np.mgrid[0:9, 0:6].T.reshape(-1, 2) * .020
size = (1088, 1280)
cv2.setNumThreads(2)

def stats(values):
    values = np.asarray(values, dtype=float).reshape(-1)
    return dict(count=len(values), median_px=float(np.median(values)), p95_px=float(np.percentile(values, 95)),
                rms_px=float(np.sqrt(np.mean(values ** 2))), max_px=float(np.max(values))) if len(values) else dict(count=0)

def matrices(R, T):
    return cv2.fisheye.stereoRectify(K[0], D[0], K[1], D[1], size, R, T,
        flags=cv2.CALIB_ZERO_DISPARITY, newImageSize=size, balance=0.0)

def vertical(points, rectification):
    rotations = rectification[:2]
    projections = rectification[2:4]
    rectified = [cv2.fisheye.undistortPoints(points[eye].reshape(-1, 1, 2), K[eye], D[eye],
                    R=rotations[eye], P=projections[eye]).reshape(-1, 2) for eye in (0, 1)]
    return np.abs(rectified[0][:, 1] - rectified[1][:, 1])

models = {
    'factory': (factory_R, factory_T, matrices(factory_R, factory_T)),
    'frozen_candidate': (candidate_R, candidate_T, matrices(candidate_R, candidate_T)),
}
all_errors = {name: [] for name in models}
prediction_errors = {name: [] for name in models}
all_corners = [[], []]
all_centers = [[], []]
mono_errors = [[], []]
records = []
point_rows = []
for observation in inspection['observations']:
    if not observation['both_found']:
        continue
    points = [np.array(item['corners'], dtype=np.float64) for item in observation['eyes']]
    # Resolve only the physical checkerboard's 180-degree label ambiguity, using the original factory model.
    forward = vertical(points, models['factory'][2])
    backward = vertical([points[0], points[1][::-1].copy()], models['factory'][2])
    reversed_left = bool(np.median(backward) < np.median(forward))
    if reversed_left:
        points[1] = points[1][::-1].copy()
    poses = []
    for eye in (0, 1):
        normalized = cv2.fisheye.undistortPoints(points[eye].reshape(-1, 1, 2), K[eye], D[eye])
        ok, r, t = cv2.solvePnP(objects, normalized, np.eye(3), None, flags=cv2.SOLVEPNP_ITERATIVE)
        assert ok
        projected = cv2.fisheye.projectPoints(objects, r, t, K[eye], D[eye])[0].reshape(-1, 2)
        errors = np.linalg.norm(projected - points[eye], axis=1)
        mono_errors[eye].extend(errors.tolist())
        all_corners[eye].append(points[eye])
        all_centers[eye].append(np.mean(points[eye], axis=0) / np.array(size))
        poses.append((cv2.Rodrigues(r)[0], t.reshape(3), stats(errors)))
    record = dict(pair_id=observation['pair_id'], reversed_left_labels=reversed_left,
                  mono_pose_reprojection=[pose[2] for pose in poses], models={})
    for name, (R, T, rectification) in models.items():
        error = vertical(points, rectification)
        all_errors[name].extend(error.tolist())
        board_R = R @ poses[0][0]
        board_T = R @ poses[0][1] + T
        projected = cv2.fisheye.projectPoints(objects, cv2.Rodrigues(board_R)[0], board_T.reshape(3, 1), K[1], D[1])[0].reshape(-1, 2)
        prediction_error = np.linalg.norm(projected - points[1], axis=1)
        prediction_errors[name].extend(prediction_error.tolist())
        record['models'][name] = dict(vertical_error=stats(error),
            cam0_pose_to_cam1_prediction=stats(prediction_error))
        for corner, value in enumerate(error):
            point_rows.append([observation['pair_id'], corner, name, *points[0][corner], *points[1][corner], float(value)])
    records.append(record)

assert records, 'No complete target pair found; no geometry claim allowed'
coverage = []
for eye in (0, 1):
    corners = np.concatenate(all_corners[eye]).astype(np.float32)
    centers = np.array(all_centers[eye])
    grid = np.zeros((3, 3), dtype=int)
    for x, y in centers:
        grid[min(2, int(y*3)), min(2, int(x*3))] += 1
    coverage.append(dict(eye=eye,
        corner_hull_image_fraction=float(cv2.contourArea(cv2.convexHull(corners)) / (1088*1280)),
        center_min=centers.min(axis=0).tolist(), center_max=centers.max(axis=0).tolist(),
        center_span=(centers.max(axis=0)-centers.min(axis=0)).tolist(),
        center_grid_3x3=grid.tolist(),
        mono_pose_reprojection=stats(mono_errors[eye])))

metrics = {name: dict(vertical_error=stats(errors),
            vertical_error_at_common_650px_focal=stats(np.array(errors)*650/models[name][2][2][0, 0]),
            virtual_focal_px=float(models[name][2][2][0, 0]),
            cam0_pose_to_cam1_prediction=stats(prediction_errors[name])) for name, errors in all_errors.items()}
# Project-specific diagnostic gates, not a claimed external certification or a live-VIO gate.
criteria = dict(minimum_complete_pairs=15, required_corner_hull_fraction_per_eye=.60,
                required_center_span_each_axis=.45, maximum_median_at_650px_focal=.5,
                maximum_p95_at_650px_focal=1.0)
coverage_pass = all(c['corner_hull_image_fraction'] >= .60 and min(c['center_span']) >= .45 for c in coverage)
error_values = metrics['frozen_candidate']['vertical_error_at_common_650px_focal']
epipolar_pass = len(records) >= 15 and error_values['median_px'] <= .5 and error_values['p95_px'] <= 1.0
result = dict(status='independent_validation_completed_no_refit', capture_session=args.session,
    input_source=inspection.get('input_source', 'V4L2_RAW10_converted_to_mono8'),
    source_training_session='target-sweep-20261014',
    frozen_candidate_sha256_before_capture=transaction['frozen_candidate_sha256'],
    frozen_candidate_sha256_after_evaluation=hashlib.sha256(parameters_path.read_bytes()).hexdigest(),
    candidate_unchanged=True, parameter_optimization_or_refit_performed=False,
    sampled_pairs=inspection['sampled_pairs'], complete_target_pairs=len(records),
    corner_count=54*len(records), metrics=metrics, coverage=coverage,
    project_specific_diagnostic_criteria=criteria, coverage_gate_passed=coverage_pass,
    epipolar_error_gate_passed=epipolar_pass,
    full_field_diagnostic_gate_passed=coverage_pass and epipolar_pass,
    live_VIO_accepted=False, camera_IMU_calibration_complete=False,
    RAW_sensor_calibration_acceptance=False,
    observations=records,
    limitations=['Checkerboard physical size/flatness relies on the user-confirmed 20mm flat target.',
                'Mono board poses are fitted for diagnostics; K/D and stereo R/T are frozen.',
                'Every complete detected target is included; no residual-based rejection is used.',
                'Motion blur, missed corners and exposure skew can affect error; no common exposure/IMU time is certified.',
                'Spatial hull and center span are coverage diagnostics; they do not alone prove dense field accuracy.'])
(output / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
with (output / 'corner-errors.csv').open('w', newline='') as stream:
    writer = csv.writer(stream)
    writer.writerow(['pair_id', 'corner', 'model', 'cam0_x', 'cam0_y', 'cam1_x', 'cam1_y', 'vertical_error_px'])
    writer.writerows(point_rows)
assert parameters_hash == hashlib.sha256(parameters_path.read_bytes()).hexdigest()
print(json.dumps({key: result[key] for key in ['status', 'complete_target_pairs', 'metrics', 'coverage',
                 'coverage_gate_passed', 'epipolar_error_gate_passed', 'full_field_diagnostic_gate_passed']}), flush=True)
