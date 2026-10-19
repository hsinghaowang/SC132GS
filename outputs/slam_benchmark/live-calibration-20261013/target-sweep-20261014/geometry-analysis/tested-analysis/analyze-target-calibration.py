"""Offline target validation and a held-out, fixed-intrinsics stereo candidate."""
import argparse
import hashlib
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
output.mkdir(exist_ok=False)
inspection = json.loads((root / 'target-coverage/report.json').read_text())
calibration = json.loads((base / 'factory-calibration-20261013/raw-intrinsics.json').read_text())
K = [np.array(calibration['cameras'][f'cam{eye}']['K'], dtype=np.float64) for eye in (0, 1)]
D = [np.array(calibration['cameras'][f'cam{eye}']['distortion_coeffs'], dtype=np.float64) for eye in (0, 1)]
size = (1088, 1280)
factory_R = np.array(calibration['stereo_factory_raw']['rotation_left_to_right'], dtype=np.float64).T
factory_T = -factory_R @ np.array(calibration['stereo_factory_raw']['translation_left_to_right'], dtype=np.float64)
objects = np.zeros((54, 1, 3), dtype=np.float64)
objects[:, 0, :2] = np.mgrid[0:9, 0:6].T.reshape(-1, 2) * 0.020
cv2.setNumThreads(2)

def stats(values):
    values = np.asarray(values, dtype=float).reshape(-1)
    return dict(count=len(values), median_px=float(np.median(values)), p95_px=float(np.percentile(values, 95)),
                rms_px=float(np.sqrt(np.mean(values ** 2))), max_px=float(np.max(values))) if len(values) else dict(count=0)

def rectify(R, T):
    return cv2.fisheye.stereoRectify(K[0], D[0], K[1], D[1], size, R, T,
             flags=cv2.CALIB_ZERO_DISPARITY, newImageSize=size, balance=0.0)

factory_rectification = rectify(factory_R, factory_T)

def vertical(points, matrices):
    r0, r1, p0, p1, _ = matrices
    rectified = [cv2.fisheye.undistortPoints(points[eye].reshape(-1, 1, 2), K[eye], D[eye],
                   R=[r0, r1][eye], P=[p0, p1][eye]).reshape(-1, 2) for eye in (0, 1)]
    return np.abs(rectified[0][:, 1] - rectified[1][:, 1])

def pose(points, eye):
    normalized = cv2.fisheye.undistortPoints(points.reshape(-1, 1, 2), K[eye], D[eye])
    ok, rotation, translation = cv2.solvePnP(objects, normalized, np.eye(3), None, flags=cv2.SOLVEPNP_ITERATIVE)
    assert ok and translation[2, 0] > 0
    projected = cv2.fisheye.projectPoints(objects, rotation, translation, K[eye], D[eye])[0].reshape(-1, 2)
    return cv2.Rodrigues(rotation)[0], translation.reshape(3), np.linalg.norm(projected - points, axis=1)

observations = []
all_points = [[], []]
per_eye_errors = [[], []]
for row in inspection['observations']:
    if not row['both_found']:
        continue
    points = [np.array(eye['corners'], dtype=np.float64) for eye in row['eyes']]
    # A plain rectangular chessboard has a 180-degree label ambiguity; only that permutation is allowed.
    forward = vertical(points, factory_rectification)
    reverse = vertical([points[0], points[1][::-1].copy()], factory_rectification)
    reversed_left = bool(np.median(reverse) < np.median(forward))
    if reversed_left:
        points[1] = points[1][::-1].copy()
    poses = [pose(points[eye], eye) for eye in (0, 1)]
    for eye in (0, 1):
        all_points[eye].append(points[eye])
        per_eye_errors[eye].extend(poses[eye][2].tolist())
    normal = poses[0][0][:, 2]
    record = dict(pair_id=row['pair_id'], points=points,
                  reversed_left_checkerboard_labels=reversed_left,
                  center_normalized=np.mean(points[0], axis=0) / np.array(size),
                  area_fraction=row['eyes'][0]['area_fraction'], normal=normal,
                  tilt_deg=float(np.degrees(np.arccos(np.clip(abs(normal[2]), 0, 1)))),
                  mono_pose_reprojection=[stats(item[2]) for item in poses],
                  poses=poses,
                  factory_vertical_error=stats(vertical(points, factory_rectification)))
    observations.append(record)

assert len(observations) >= 3, 'Too few target pairs even for diagnostic'
unique = []
for index, observation in enumerate(observations):
    redundant = False
    for old_index in unique:
        old = observations[old_index]
        center_distance = np.linalg.norm(observation['center_normalized'] - old['center_normalized'])
        log_area_change = abs(np.log(observation['area_fraction'] / old['area_fraction']))
        normal_angle = np.degrees(np.arccos(np.clip(np.dot(observation['normal'], old['normal']), -1, 1)))
        if center_distance < .06 and log_area_change < .25 and normal_angle < 10:
            redundant = True
            break
    if not redundant:
        unique.append(index)
holdout = unique[::4]
training = [index for index in unique if index not in holdout]
centers = np.array([observation['center_normalized'] for observation in observations])
coverage = dict(complete_pairs=len(observations), diverse_pose_representatives=len(unique),
    training_pose_representatives=len(training), held_out_pose_representatives=len(holdout),
    center_min=centers.min(axis=0).tolist(), center_max=centers.max(axis=0).tolist(),
    corner_hull_image_fraction=[float(cv2.contourArea(cv2.convexHull(np.concatenate(points).astype(np.float32))) / (size[0]*size[1])) for points in all_points],
    board_area_fraction_range=[float(min(o['area_fraction'] for o in observations)), float(max(o['area_fraction'] for o in observations))],
    tilt_deg_range=[float(min(o['tilt_deg'] for o in observations)), float(max(o['tilt_deg'] for o in observations))],
    pose_selection='Greedy: center change >=0.06 frame, log area change >=0.25 or normal angle >=10deg; held-out every fourth representative, whole observations withheld')
print(json.dumps(dict(coverage=coverage)), flush=True)

def errors_for_model(rotation, translation):
    matrices = rectify(rotation, translation)
    result = {}
    for label, indices in [('all_complete', list(range(len(observations)))), ('training', training), ('held_out', holdout)]:
        epipolar = []
        reprojection = []
        positive = 0
        for index in indices:
            observation = observations[index]
            epipolar.extend(vertical(observation['points'], matrices).tolist())
            board_R0, board_T0, _ = observation['poses'][0]
            board_R1 = rotation @ board_R0
            board_T1 = rotation @ board_T0 + translation
            xyz = objects.reshape(-1, 3) @ board_R1.T + board_T1
            positive += int(np.sum(xyz[:, 2] > 0))
            projected = cv2.fisheye.projectPoints(objects, cv2.Rodrigues(board_R1)[0], board_T1.reshape(3, 1), K[1], D[1])[0].reshape(-1, 2)
            reprojection.extend(np.linalg.norm(projected - observation['points'][1], axis=1).tolist())
        result[label] = dict(pairs=len(indices), vertical_error=stats(epipolar),
            vertical_error_at_650px_focal=stats(np.array(epipolar) * 650 / matrices[2][0, 0]),
            cam0_pose_to_cam1_prediction_error=stats(reprojection),
            positive_predicted_depth_fraction=positive / (54*len(indices)) if indices else None)
    return result, matrices

factory_errors, _ = errors_for_model(factory_R, factory_T)
result = dict(status='factory_target_validation_completed', session=args.session, opencv_version=cv2.__version__,
    target=inspection['target'], coverage=coverage,
    intrinsics_modified=False, factory_EEPROM_modified=False,
    factory_mono_pose_reprojection=[stats(errors) for errors in per_eye_errors],
    factory_stereo=dict(R_cam1_cam0=factory_R.tolist(), T_cam1_cam0_raw_units=factory_T.tolist(), errors=factory_errors,
        translation_scale_for_cross_camera_prediction='Provisionally treating raw translation as meters; conditional on 20mm physical square size'),
    candidate=None, geometric_calibration_accepted_for_live_VIO=False,
    limitations=['Physical square spacing is nominal 20mm; user metrology and board flatness are not independently verified.',
                 'Board poses are fitted to the same images using fixed factory intrinsics; mono residuals do not establish broad independent intrinsic accuracy.',
                 'Held-out poses come from one capture session and do not replace a separate validation session.',
                 'Camera receive timestamps are not exposure start; moving-board mismatch can include exposure skew.',
                 'Camera-IMU extrinsics, common timebase and noise calibration remain pending.'])
if len(training) >= 8 and len(holdout) >= 3:
    object_sets = [objects.copy() for _ in training]
    image_sets = [[observations[index]['points'][eye].reshape(-1, 1, 2).copy() for index in training] for eye in (0, 1)]
    try:
        rms, k0, d0, k1, d1, R, T = cv2.fisheye.stereoCalibrate(object_sets, image_sets[0], image_sets[1],
            K[0].copy(), D[0].copy(), K[1].copy(), D[1].copy(), size,
            flags=cv2.fisheye.CALIB_FIX_INTRINSIC,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 150, 1e-9))
        assert np.array_equal(k0, K[0]) and np.array_equal(k1, K[1])
        assert np.array_equal(d0.reshape(-1), D[0]) and np.array_equal(d1.reshape(-1), D[1])
        T = T.reshape(3)
        candidate_errors, candidate_matrices = errors_for_model(R, T)
        delta_angle = float(np.degrees(np.linalg.norm(cv2.Rodrigues(R @ factory_R.T)[0])))
        result['candidate'] = dict(status='fixed_intrinsics_stereo_candidate_not_deployed', training_rms_px=float(rms),
            training_pair_ids=[observations[index]['pair_id'] for index in training],
            held_out_pair_ids=[observations[index]['pair_id'] for index in holdout],
            R_cam1_cam0=R.tolist(), T_cam1_cam0_m_assuming_20mm_squares=T.tolist(),
            baseline_m_assuming_20mm_squares=float(np.linalg.norm(T)),
            rotation_difference_from_factory_deg=delta_angle,
            factory_intrinsics_unchanged=True, errors=candidate_errors)
        np.savez_compressed(output / 'stereo-candidate.npz', K0=K[0], D0=D[0], K1=K[1], D1=D[1],
            R_cam1_cam0=R, T_cam1_cam0_m_assuming_20mm_squares=T,
            R0=candidate_matrices[0], R1=candidate_matrices[1], P0=candidate_matrices[2], P1=candidate_matrices[3])
    except (cv2.error, AssertionError) as error:
        result['candidate'] = dict(status='fit_failed_preserve_factory', error=str(error))
else:
    result['candidate'] = dict(status='not_fitted_insufficient_diverse_training_and_holdout_poses')

serialized = []
for observation in observations:
    serialized.append({key: value for key, value in observation.items() if key not in ['points', 'poses', 'normal', 'center_normalized']})
result['observations'] = serialized
(output / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({key: value for key, value in result.items() if key != 'observations'}), flush=True)
