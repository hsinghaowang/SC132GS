"""Offline geometry diagnostic on saved physical images. Never accesses sensors."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import time

import cv2
import numpy as np


def summarize(values):
    values = np.asarray(values, dtype=float)
    if values.size == 0:
        return dict(count=0)
    return dict(count=int(values.size), median_px=float(np.median(values)),
                p95_px=float(np.percentile(values, 95)), max_px=float(np.max(values)),
                fraction_le_1px=float(np.mean(values <= 1)),
                fraction_le_2px=float(np.mean(values <= 2)))


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def rectify_points(points, K, D, rotation, projection):
    return cv2.fisheye.undistortPoints(points.reshape(-1, 1, 2), K, D,
                                     R=rotation, P=projection).reshape(-1, 2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--samples', type=int, default=10)
    parser.add_argument('--output-name', default='factory-geometry-20261013')
    parser.add_argument('--full-resolution', action='store_true')
    parser.add_argument('--refine-appearance', action='store_true')
    args = parser.parse_args()
    started = time.monotonic()
    root = args.root
    out = root / args.output_name
    out.mkdir(exist_ok=False)
    calibration_path = root / 'factory-calibration-20261013/raw-intrinsics.json'
    calibration = json.loads(calibration_path.read_text())
    session = root / 'live-calibration-20261013/paired-10s'
    rows = list(csv.DictReader((session / 'camera-frames.csv').open()))
    pairs = {}
    for row in rows:
        pairs.setdefault(int(row['pair_id']), {})[int(row['eye'])] = row
    complete = [pair for _, pair in sorted(pairs.items()) if set(pair) == {0, 1}]
    selected = np.linspace(0, len(complete) - 1, min(args.samples, len(complete)), dtype=int)
    size = tuple(calibration['cameras']['cam0']['resolution'])
    K = [np.array(calibration['cameras'][f'cam{eye}']['K'], dtype=np.float64) for eye in (0, 1)]
    D = [np.array(calibration['cameras'][f'cam{eye}']['distortion_coeffs'], dtype=np.float64) for eye in (0, 1)]
    R_left_right = np.array(calibration['stereo_factory_raw']['rotation_left_to_right'], dtype=np.float64)
    T_left_right = np.array(calibration['stereo_factory_raw']['translation_left_to_right'], dtype=np.float64)
    # OpenCV camera1=cam0(right), camera2=cam1(left): invert the factory left->right pose.
    R_right_left = R_left_right.T
    T_right_left = -R_right_left @ T_left_right
    transform = np.eye(4)
    transform[:3, :3] = R_right_left
    transform[:3, 3] = T_right_left
    factory_transform = np.eye(4)
    factory_transform[:3, :3] = R_left_right
    factory_transform[:3, 3] = T_left_right
    assert np.max(np.abs(transform @ factory_transform - np.eye(4))) < 1e-7

    def rectification(R, T, distortion):
        return cv2.fisheye.stereoRectify(K[0], distortion[0], K[1], distortion[1], size,
            R, T, flags=cv2.CALIB_ZERO_DISPARITY, newImageSize=size, balance=0.0, fov_scale=1.0)

    correct = rectification(R_right_left, T_right_left, D)
    wrong_direction = rectification(R_left_right, T_left_right, D)
    no_distortion = rectification(R_right_left, T_right_left, [np.zeros(4), np.zeros(4)])
    controls = [('factory', correct, D), ('alternative_transform_direction', wrong_direction, D),
                ('ignore_fisheye_distortion', no_distortion, [np.zeros(4), np.zeros(4)])]
    R0, R1, P0, P1, Q = correct
    maps = [cv2.fisheye.initUndistortRectifyMap(K[eye], D[eye], [R0, R1][eye],
        [P0, P1][eye], size, cv2.CV_32FC1) for eye in (0, 1)]

    # Matches are chosen by image appearance only, before reading any epipolar residual.
    # Compute SIFT on half-size images for bounded diagnostic cost; coordinates return to RAW pixels.
    cv2.setNumThreads(2)
    cv2.setRNGSeed(20261013)
    sift = cv2.SIFT_create(nfeatures=2500)
    matcher = cv2.BFMatcher(cv2.NORM_L2)
    all_residuals = {name: [] for name, _, _ in controls}
    all_inlier_residuals = {name: [] for name, _, _ in controls}
    raw_residuals = []
    results = []
    manifest = {}
    sample_match_csv = []
    chosen_preview = None
    full_target_pairs = 0
    for selected_index in selected:
        pair = complete[int(selected_index)]
        paths = [session / pair[eye]['image'] for eye in (0, 1)]
        images = [cv2.imread(str(path), cv2.IMREAD_GRAYSCALE) for path in paths]
        assert all(image is not None and image.shape[::-1] == size for image in images)
        for path in paths:
            manifest[str(path.relative_to(root))] = sha256(path)
        scale = 1.0 if args.full_resolution else 0.5
        thumbnails = [image if args.full_resolution else cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) for image in images]
        features = [sift.detectAndCompute(image, None) for image in thumbnails]
        if any(item[1] is None for item in features):
            results.append(dict(pair_id=int(pair[0]['pair_id']), status='insufficient_features'))
            continue
        kp0, descriptors0 = features[0]
        kp1, descriptors1 = features[1]
        forward = {m.queryIdx: m for group in matcher.knnMatch(descriptors0, descriptors1, k=2)
                   if len(group) == 2 for m, n in [group] if m.distance < 0.75 * n.distance}
        backward = {m.queryIdx: m.trainIdx for group in matcher.knnMatch(descriptors1, descriptors0, k=2)
                    if len(group) == 2 for m, n in [group] if m.distance < 0.75 * n.distance}
        mutual = [m for m in forward.values() if backward.get(m.trainIdx) == m.queryIdx]
        points = [np.array([features[eye][0][m.queryIdx if eye == 0 else m.trainIdx].pt
                  for m in mutual], dtype=np.float64).reshape(-1, 2) / scale for eye in (0, 1)]
        mutual_before_refinement = len(mutual)
        if args.refine_appearance and mutual:
            original0 = points[0].astype(np.float32).reshape(-1, 1, 2)
            original1 = points[1].astype(np.float32).reshape(-1, 1, 2)
            parameters = dict(winSize=(21, 21), maxLevel=2,
                              criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 40, 0.001),
                              flags=cv2.OPTFLOW_USE_INITIAL_FLOW)
            tracked1, status1, _ = cv2.calcOpticalFlowPyrLK(images[0], images[1], original0,
                                                          original1.copy(), **parameters)
            returned0, status0, _ = cv2.calcOpticalFlowPyrLK(images[1], images[0], tracked1,
                                                           original0.copy(), **parameters)
            initial_shift = np.linalg.norm(tracked1.reshape(-1, 2) - original1.reshape(-1, 2), axis=1)
            forward_backward_error = np.linalg.norm(returned0.reshape(-1, 2) - original0.reshape(-1, 2), axis=1)
            keep = status0.reshape(-1).astype(bool) & status1.reshape(-1).astype(bool)
            keep &= (initial_shift <= 3.0) & (forward_backward_error <= 0.5)
            points = [points[0][keep], tracked1.reshape(-1, 2)[keep].astype(np.float64)]
            mutual = [match for match, accepted in zip(mutual, keep) if accepted]
        if len(mutual) < 8:
            results.append(dict(pair_id=int(pair[0]['pair_id']), status='insufficient_matches', mutual_matches=len(mutual)))
            continue
        # Independent fitted F rejects repetitive-texture mismatches. It is not the factory F.
        # Preserve ALL appearance matches as primary evidence so factory failures are never silently gated away.
        virtual = [cv2.fisheye.undistortPoints(points[eye].reshape(-1, 1, 2), K[eye], D[eye],
                    P=K[0]).reshape(-1, 2) for eye in (0, 1)]
        fitted_F, mask = cv2.findFundamentalMat(virtual[0], virtual[1], cv2.FM_RANSAC, 1.0, 0.999)
        inliers = np.zeros(len(mutual), dtype=bool) if mask is None else mask.reshape(-1).astype(bool)
        record = dict(pair_id=int(pair[0]['pair_id']), status='evaluated', mutual_matches=len(mutual),
                      mutual_matches_before_appearance_refinement=mutual_before_refinement,
                      independently_fitted_F_inliers=int(inliers.sum()),
                      receiver_delta_ms=abs(int(pair[0]['receiver_timestamp_ns']) - int(pair[1]['receiver_timestamp_ns'])) / 1e6,
                      raw_vertical_residual=summarize(np.abs(points[0][:, 1] - points[1][:, 1])), controls={})
        raw_residuals.extend(np.abs(points[0][:, 1] - points[1][:, 1]).tolist())
        rectified_points = None
        for name, (rotation0, rotation1, projection0, projection1, _), distortion in controls:
            rect0 = rectify_points(points[0], K[0], distortion[0], rotation0, projection0)
            rect1 = rectify_points(points[1], K[1], distortion[1], rotation1, projection1)
            residual = np.abs(rect0[:, 1] - rect1[:, 1])
            all_residuals[name].extend(residual.tolist())
            all_inlier_residuals[name].extend(residual[inliers].tolist())
            record['controls'][name] = dict(all_appearance_matches=summarize(residual),
                independently_fitted_F_subset=summarize(residual[inliers]),
                virtual_focal_px=float(projection0[0, 0]),
                all_appearance_matches_at_common_650px_focal=summarize(residual * 650.0 / projection0[0, 0]))
            if name == 'factory':
                rectified_points = [rect0, rect1]
                for i, value in enumerate(residual):
                    sample_match_csv.append([record['pair_id'], *points[0][i], *points[1][i],
                                             *rect0[i], *rect1[i], float(value), int(inliers[i])])
        # Target presence check on each sampled physical frame; no target is manufactured.
        target = [bool(cv2.findChessboardCorners(image, (9, 6),
                    cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE | cv2.CALIB_CB_FAST_CHECK)[0])
                  for image in images]
        full_target_pairs += int(all(target))
        record['checkerboard_detected'] = target
        results.append(record)
        if chosen_preview is None:
            chosen_preview = (images, rectified_points, inliers, record['pair_id'])
        print(json.dumps(dict(completed=len(results), total=len(selected), pair=record['pair_id'],
                             matches=len(mutual), factory_median_px=record['controls']['factory']['all_appearance_matches']['median_px'])), flush=True)

    if chosen_preview:
        images, points, inliers, pair_id = chosen_preview
        rectified = [cv2.remap(images[eye], *maps[eye], cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_CONSTANT) for eye in (0, 1)]
        raw_canvas = np.hstack(images)
        rect_canvas = np.hstack(rectified)
        for image, name in [(raw_canvas, 'raw-pair.png'), (rect_canvas, 'rectified-pair.png')]:
            canvas = cv2.cvtColor(cv2.resize(image, None, fx=0.5, fy=0.5), cv2.COLOR_GRAY2BGR)
            for y in range(32, canvas.shape[0], 48):
                cv2.line(canvas, (0, y), (canvas.shape[1] - 1, y), (0, 190, 255), 1)
            label = f'cam0 RIGHT | cam1 LEFT; {name}; pair {pair_id}'
            cv2.putText(canvas, label, (12, 24), cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 255, 255), 1, cv2.LINE_AA)
            assert cv2.imwrite(str(out / name), canvas)
        for eye in (0, 1):
            assert cv2.imwrite(str(out / f'rectified-cam{eye}.png'), rectified[eye])

    np.savez_compressed(out / 'rectification-matrices.npz', R0=R0, R1=R1, P0=P0, P1=P1, Q=Q,
                        T_cam1_cam0=transform, T_cam0_cam1=factory_transform)
    with (out / 'appearance-matches.csv').open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['pair_id', 'raw0_x', 'raw0_y', 'raw1_x', 'raw1_y', 'rect0_x',
                         'rect0_y', 'rect1_x', 'rect1_y', 'abs_vertical_px', 'fitted_F_inlier'])
        writer.writerows(sample_match_csv)
    report = dict(status='offline_epipolar_diagnostic_completed', opencv_version=cv2.__version__,
        elapsed_seconds=time.monotonic() - started,
        input_calibration_sha256=sha256(calibration_path),
        camera_resolution=list(size), available_pairs=len(complete), sampled_pairs=len(results),
        complete_checkerboard_pairs=full_target_pairs,
        coordinate_convention='cam0=right 0x32; cam1=left 0x30; p_cam1=R_lr.T*p_cam0 - R_lr.T*T_lr',
        transform_inverse_max_error=float(np.max(np.abs(transform @ factory_transform - np.eye(4)))),
        rotation_orthogonality_max_error=float(np.max(np.abs(R_left_right.T @ R_left_right - np.eye(3)))),
        rotation_determinant=float(np.linalg.det(R_left_right)),
        factory_translation_raw=T_left_right.tolist(), factory_translation_norm_raw=float(np.linalg.norm(T_left_right)),
        translation_units_independently_verified=False,
        T_cam1_cam0_raw_units=transform.tolist(),
        method='SIFT, mutual ratio0.75, coordinates in full RAW pixels; no factory geometry gate; independent F-RANSAC secondary subset',
        SIFT_detection_scale=scale, appearance_refinement=args.refine_appearance,
        appearance_refinement_parameters={'LK_window': [21, 21], 'max_initial_shift_px': 3.0,
                                           'max_forward_backward_error_px': 0.5} if args.refine_appearance else None,
        raw_vertical_residual=summarize(raw_residuals),
        controls={name: dict(all_appearance_matches=summarize(all_residuals[name]),
                  independently_fitted_F_subset=summarize(all_inlier_residuals[name]),
                  virtual_focal_px=float(matrices[2][0, 0]),
                  all_appearance_matches_at_common_650px_focal=summarize(np.array(all_residuals[name]) * 650.0 / matrices[2][0, 0])) for name, matrices, _ in controls},
        pairs=results,
        calibration_reprojection_precision_validated=False,
        camera_IMU_extrinsics_or_time_validated=False,
        live_VIO_performed=False,
        sensor_access=False,
        limitations=['Natural-scene check uses repeated frames of one mostly stationary viewpoint, not calibration-target coverage.',
                    'Subpixel epipolar residual does not prove intrinsics, metric depth scale, exposure synchronization or camera-IMU timing.',
                    'All appearance matches include mismatches; fitted F subset can hide systematic error and is reported separately.',
                    'Wrong-direction and zero-distortion controls have different virtual focal lengths; pixel residuals must be read with focal scale.',
                    'Rectification depends on translation direction, not its metric scale; depth/baseline units remain independently unverified.'])
    write_json(out / 'report.json', report)
    write_json(out / 'input-sha256.json', manifest)
    print(json.dumps({key: report[key] for key in ['status', 'elapsed_seconds', 'sampled_pairs', 'complete_checkerboard_pairs', 'controls']}), flush=True)


if __name__ == '__main__':
    main()
