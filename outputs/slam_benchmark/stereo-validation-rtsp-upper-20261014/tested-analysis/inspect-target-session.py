"""Check physical chessboard observations without fitting calibration."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument('session')
parser.add_argument('--samples', type=int, default=3)
parser.add_argument('--output', default='target-inspection')
parser.add_argument('--base', type=Path, default=Path('/ws/slam_benchmark'))
parser.add_argument('--input-source', default='V4L2_RAW10_converted_to_mono8')
args = parser.parse_args()
base = args.base
root = base / 'live-calibration-20261013' / args.session
output = root / args.output
output.mkdir(exist_ok=False)
rows = list(csv.DictReader((root / 'camera-frames.csv').open()))
pairs = {}
for row in rows:
    pairs.setdefault(int(row['pair_id']), {})[int(row['eye'])] = row
identifiers = sorted(key for key, pair in pairs.items() if set(pair) == {0, 1})
indices = np.linspace(0, len(identifiers) - 1, min(args.samples, len(identifiers)), dtype=int)
cv2.setNumThreads(2)
records = []
for index in indices:
    pair_id = identifiers[int(index)]
    eyes = []
    marked = []
    for eye in (0, 1):
        path = root / pairs[pair_id][eye]['image']
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        assert image is not None
        found, corners = cv2.findChessboardCorners(image, (9, 6),
            cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE | cv2.CALIB_CB_FAST_CHECK)
        method = 'classic'
        if not found:
            found, corners = cv2.findChessboardCornersSB(image, (9, 6), cv2.CALIB_CB_NORMALIZE_IMAGE)
            method = 'SB'
        result = dict(eye=eye, found=bool(found), detector=method,
                      image=str(path.relative_to(root)), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        canvas = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        if found:
            if method == 'classic':
                corners = cv2.cornerSubPix(image, corners, (5, 5), (-1, -1),
                         (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 40, 0.001))
            points = corners.reshape(-1, 2)
            result.update(corners=points.tolist(), area_fraction=float(cv2.contourArea(cv2.convexHull(points)) / image.size),
                          center_normalized=(np.mean(points, axis=0) / np.array(image.shape[::-1])).tolist(),
                          sharpness_laplacian_variance=float(cv2.Laplacian(image, cv2.CV_64F).var()))
            cv2.drawChessboardCorners(canvas, (9, 6), corners, found)
        cv2.putText(canvas, f'cam{eye}: 9x6 found={found}; pair={pair_id}', (15, 35),
                    cv2.FONT_HERSHEY_SIMPLEX, .7, (0, 220, 255), 2)
        marked.append(canvas)
        eyes.append(result)
    preview = cv2.resize(np.hstack(marked), None, fx=.5, fy=.5, interpolation=cv2.INTER_AREA)
    assert cv2.imwrite(str(output / f'pair-{pair_id}.png'), preview)
    records.append(dict(pair_id=pair_id, eyes=eyes, both_found=all(eye['found'] for eye in eyes)))
    print(json.dumps(dict(pair_id=pair_id, found=[eye['found'] for eye in eyes])), flush=True)
report = dict(session=args.session, input_source=args.input_source, sampled_pairs=len(records), stereo_target_pairs=sum(row['both_found'] for row in records),
              target=dict(inner_corners=[9, 6], square_size_m_nominal=.020, physical_square_measurement_verified=False),
              observations=records, calibration_fitted=False)
(output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({key: report[key] for key in ['session', 'sampled_pairs', 'stereo_target_pairs']}), flush=True)
