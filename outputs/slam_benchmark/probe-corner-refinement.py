"""Bounded detector comparison on saved images; no refit, rejection or camera access."""
import csv
import hashlib
import json
from pathlib import Path
import shutil

import cv2
import numpy as np

base = Path(__file__).resolve().parent
root = base / 'stereo-validation-rtsp-upper-20261014'
session = base / 'live-calibration-20261013/target-rtsp-upper-20261014'
output = root / 'corner-refinement-probe'
output.mkdir(exist_ok=False)
cv2.setNumThreads(2)
report = json.loads((root / 'evaluation/report.json').read_text())
inspection = json.loads((session / 'target-coverage/report.json').read_text())
by_id = {entry['pair_id']: entry for entry in inspection['observations']}
worst = sorted(report['observations'], key=lambda x: x['models']['frozen_candidate']['vertical_error']['max_px'], reverse=True)[:4]
eligible = [entry for entry in report['observations'] if entry['models']['frozen_candidate']['vertical_error']['max_px'] < 1]
controls = [eligible[int(i)] for i in np.linspace(0, len(eligible)-1, 4, dtype=int)]
selection = [('largest_prior_errors', entry) for entry in worst] + [('bounded_controls', entry) for entry in controls]
parameter_path = root / 'frozen-candidate.npz'
parameter_hash = hashlib.sha256(parameter_path.read_bytes()).hexdigest()
parameters = np.load(parameter_path)
K = [parameters[f'K{eye}'] for eye in (0, 1)]
D = [parameters[f'D{eye}'] for eye in (0, 1)]
R = parameters['R_cam1_cam0']
T = parameters['T_cam1_cam0_m_assuming_20mm_squares']
r0, r1, p0, p1, _ = cv2.fisheye.stereoRectify(K[0], D[0], K[1], D[1], (1088,1280), R, T,
    flags=cv2.CALIB_ZERO_DISPARITY, newImageSize=(1088,1280), balance=0)


def stats(values):
    values = np.asarray(values, dtype=float)
    return dict(median=float(np.median(values)), p95=float(np.percentile(values, 95)), maximum=float(np.max(values)))


def align(points, reference):
    points = points.reshape(-1, 2)
    if np.median(np.linalg.norm(points-reference, axis=1)) > np.median(np.linalg.norm(points[::-1]-reference, axis=1)):
        points = points[::-1].copy()
    return points


def residual(points):
    rectified = [cv2.fisheye.undistortPoints(points[eye].astype(np.float64).reshape(-1,1,2), K[eye], D[eye],
        R=[r0,r1][eye], P=[p0,p1][eye]).reshape(-1,2) for eye in (0,1)]
    return stats(np.abs(rectified[0][:,1]-rectified[1][:,1]))


records = []
for group, prior in selection:
    pair_id = prior['pair_id']
    observation = by_id[pair_id]
    references = [np.array(entry['corners'], dtype=np.float32) for entry in observation['eyes']]
    images = [cv2.imread(str(session / entry['image']), cv2.IMREAD_GRAYSCALE) for entry in observation['eyes']]
    point_sets = {name: [] for name in ['saved_original', 'classic_unrefined', 'classic_window3', 'classic_window5', 'SB_accuracy']}
    details = []
    for eye, image in enumerate(images):
        assert image is not None
        reference = references[eye]
        point_sets['saved_original'].append(reference.copy())
        found, raw = cv2.findChessboardCorners(image, (9,6), cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE | cv2.CALIB_CB_FAST_CHECK)
        detail = dict(eye=eye, original_detector=observation['eyes'][eye]['detector'], classic_found=bool(found))
        if found:
            raw = align(raw, reference)
            point_sets['classic_unrefined'].append(raw.copy())
            for window in (3,5):
                refined = cv2.cornerSubPix(image, raw.copy().reshape(-1,1,2), (window,window), (-1,-1),
                    (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,40,.001)).reshape(-1,2)
                point_sets[f'classic_window{window}'].append(refined)
                shifts = np.linalg.norm(refined-raw, axis=1)
                detail[f'window{window}_shift_from_initial_px'] = stats(shifts)
                detail[f'window{window}_shifted_above3px_indices'] = np.flatnonzero(shifts > 3).tolist()
            grid = raw.reshape(6,9,2)
            adjacent = np.r_[np.linalg.norm(np.diff(grid,axis=0),axis=2).ravel(), np.linalg.norm(np.diff(grid,axis=1),axis=2).ravel()]
            detail['adjacent_corner_spacing_px'] = stats(adjacent)
        found_sb, sb = cv2.findChessboardCornersSB(image, (9,6), cv2.CALIB_CB_NORMALIZE_IMAGE | cv2.CALIB_CB_ACCURACY)
        detail['SB_found'] = bool(found_sb)
        if found_sb:
            sb = align(sb, reference)
            point_sets['SB_accuracy'].append(sb)
            detail['SB_difference_from_saved_px'] = stats(np.linalg.norm(sb-reference,axis=1))
        details.append(detail)
    evaluated = {}
    for name, points in point_sets.items():
        if len(points) == 2:
            # Label orientation uses the prior frozen evaluation; detector alignment uses only image coordinates.
            if prior['reversed_left_labels']:
                points = [points[0],points[1][::-1].copy()]
            evaluated[name] = residual(points)
        else:
            evaluated[name] = dict(both_detected=False)
    record = dict(pair_id=pair_id, selection_group=group, original_prior_max_px=prior['models']['frozen_candidate']['vertical_error']['max_px'],
        details=details, frozen_model_vertical_error_px=evaluated)
    records.append(record)
    print(json.dumps(dict(pair_id=pair_id, group=group, residuals=evaluated)), flush=True)
assert parameter_hash == hashlib.sha256(parameter_path.read_bytes()).hexdigest()
result = dict(scope='Four largest-error saved pairs plus four bounded controls; diagnostic selection, not full-session acceptance',
    opencv_version=cv2.__version__, source='Already-saved RTSP decoded mono8 images',
    calibration_refit=False, residual_based_corner_rejection=False, camera_access=False,
    detector_order_alignment='Euclidean image-coordinate agreement; left-eye 180-degree orientation from prior evaluation',
    frozen_candidate_sha256=parameter_hash, records=records)
(output / 'report.json').write_text(json.dumps(result, indent=2)+'\n')
shutil.copyfile(Path(__file__), output / 'probe-used.py')
