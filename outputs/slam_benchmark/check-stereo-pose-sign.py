"""Offline pose-direction checks on existing appearance matches; no fitting or correction."""
import argparse
import csv
import json
from pathlib import Path

import cv2
import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
args = parser.parse_args()
root = args.root
calibration = json.loads((root / 'factory-calibration-20261013/raw-intrinsics.json').read_text())
R = np.array(calibration['stereo_factory_raw']['rotation_left_to_right'])
T = np.array(calibration['stereo_factory_raw']['translation_left_to_right'])
result = dict(status='offline_direction_diagnostic', metric_baseline_verified=False,
              factory_extrinsics_modified=False, live_configuration_created=False,
              scope='Triangulation sign and scale-normalized epipolar distance; same saved scene, no ground-truth target', runs={})

for name in ['factory-geometry-20261013', 'factory-geometry-full-20261013']:
    path = root / name
    matches = list(csv.DictReader((path / 'appearance-matches.csv').open()))
    normalized = []
    for eye in (0, 1):
        camera = calibration['cameras'][f'cam{eye}']
        points = np.array([[float(row[f'raw{eye}_x']), float(row[f'raw{eye}_y'])] for row in matches])
        normalized.append(cv2.fisheye.undistortPoints(points.reshape(-1, 1, 2),
                          np.array(camera['K']), np.array(camera['distortion_coeffs'])).reshape(-1, 2))
    masks = {'all_appearance_matches': np.ones(len(matches), dtype=bool),
             'independently_fitted_F_subset': np.array([bool(int(row['fitted_F_inlier'])) for row in matches])}
    controls = {}
    for convention, rotation, translation in [('documented_factory_inverse', R.T, -R.T @ T),
                                               ('alternative_direction_control', R, T)]:
        homogeneous = cv2.triangulatePoints(np.hstack([np.eye(3), np.zeros((3, 1))]),
                         np.hstack([rotation, translation.reshape(3, 1)]),
                         normalized[0].T, normalized[1].T)
        xyz0 = homogeneous[:3] / homogeneous[3]
        xyz1 = rotation @ xyz0 + translation.reshape(3, 1)
        finite = np.isfinite(xyz0).all(axis=0) & np.isfinite(xyz1).all(axis=0)
        positive = finite & (xyz0[2] > 0) & (xyz1[2] > 0)
        x, y, z = translation
        skew = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])
        essential = skew @ rotation
        p0 = np.column_stack([normalized[0], np.ones(len(matches))])
        p1 = np.column_stack([normalized[1], np.ones(len(matches))])
        line1 = p0 @ essential.T
        line0 = p1 @ essential
        equation = np.einsum('ij,ij->i', p1, line1)
        denominator = np.sqrt(np.sum(line1[:, :2] ** 2, axis=1) + np.sum(line0[:, :2] ** 2, axis=1))
        sampson = np.abs(equation) / np.maximum(denominator, 1e-30) * 650.0
        controls[convention] = {
            subset: dict(count=int(mask.sum()), positive_depth_fraction=float(np.mean(positive[mask])),
                         median_sampson_at_650px_focal=float(np.median(sampson[mask])),
                         p95_sampson_at_650px_focal=float(np.percentile(sampson[mask], 95)))
            for subset, mask in masks.items() if mask.any()}
    result['runs'][name] = controls

(root / 'factory-geometry-full-20261013/pose-sign-check.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
