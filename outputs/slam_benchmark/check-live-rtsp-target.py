"""A bounded corner-presence check on already saved RTSP frames, without consuming the camera."""
import json
from pathlib import Path
import sys
import cv2

base = Path(__file__).resolve().parent
session = base / 'live-calibration-20261013' / sys.argv[1]
paths = sorted((session / 'cam0').glob('*.png'), key=lambda path: int(path.stem.split('-')[0]))
assert len(paths) >= 3
name = paths[-3].name
cv2.setNumThreads(2)
found = []
for eye in (0, 1):
    image = cv2.imread(str(session / f'cam{eye}' / name), cv2.IMREAD_GRAYSCALE)
    assert image is not None
    ok, corners = cv2.findChessboardCorners(image, (9, 6),
         cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE | cv2.CALIB_CB_FAST_CHECK)
    if not ok:
        ok, corners = cv2.findChessboardCornersSB(image, (9, 6), cv2.CALIB_CB_NORMALIZE_IMAGE)
    found.append(bool(ok))
print(json.dumps(dict(file=name, found=found, checked_saved_RTSP_only=True)))
