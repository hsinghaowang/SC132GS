"""Offline stereo preview. No sensor access; no calibration fitting or hole filling."""
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

BASE = Path(__file__).resolve().parent
SOURCE = BASE / 'calibration-ready-20261014/rtsp-decode-stable/decoded.png'
CALIB = BASE / 'calibration-ready-20261014/geometry-analysis/stereo-candidate.npz'
OUT = BASE / 'depth-preview-20261015'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_image(name, pixels):
    assert cv2.imwrite(str(OUT / name), pixels), name


def summary(values):
    return dict(zip(('p05', 'median', 'p95'), map(float, np.percentile(values, [5, 50, 95])))) if len(values) else None


def main():
    cv2.setNumThreads(2)
    before = {str(p): digest(p) for p in (SOURCE, CALIB)}
    frame = cv2.imread(str(SOURCE), cv2.IMREAD_GRAYSCALE)
    assert frame is not None and frame.shape == (1280, 2176)
    # Recorded RTSP geometry: left half=cam0/right; right half=cam1/left;
    # each half horizontally mirrored. Calibration uses unmirrored RAW coordinates.
    right = cv2.flip(frame[:, :1088], 1)
    left = cv2.flip(frame[:, 1088:], 1)
    with np.load(CALIB, allow_pickle=False) as c:
        kl, dl, kr, dr = [c[k].copy() for k in ('K1', 'D1', 'K0', 'D0')]
        r10, t10 = c['R_cam1_cam0'].copy(), c['T_cam1_cam0_m_assuming_20mm_squares'].copy()
    # Invert original cam0->cam1 transform to physical left->right.
    rotation = r10.T
    translation = (-rotation @ t10.reshape(3, 1))
    size = (1088, 1280)
    rl, rr, pl, pr, q = cv2.fisheye.stereoRectify(
        kl, dl, kr, dr, size, rotation, translation,
        flags=cv2.CALIB_ZERO_DISPARITY, newImageSize=size, balance=0.0)
    assert abs(pr[0, 3]) > abs(pr[1, 3]), 'Expected horizontal stereo'
    assert pr[0, 3] < 0 and q[3, 2] > 0, 'Unexpected disparity/depth sign'
    maps = [cv2.fisheye.initUndistortRectifyMap(k, d, r, p, size, cv2.CV_32FC1)
            for k, d, r, p in ((kl, dl, rl, pl), (kr, dr, rr, pr))]
    images = [cv2.remap(im, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
              for im, (mx, my) in zip((left, right), maps)]
    supports = [(mx >= 1) & (mx < 1086) & (my >= 1) & (my < 1278) for mx, my in maps]
    supports = [cv2.erode(s.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool) for s in supports]
    settings = dict(numDisparities=256, blockSize=5, P1=8*25, P2=32*25,
                    disp12MaxDiff=1, preFilterCap=31, uniquenessRatio=10,
                    speckleWindowSize=100, speckleRange=2, mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY)
    dlpx = cv2.StereoSGBM_create(minDisparity=0, **settings).compute(*images).astype(np.float32)/16
    drpx = cv2.StereoSGBM_create(minDisparity=-255, **settings).compute(*images[::-1]).astype(np.float32)/16
    yy, xx = np.indices(dlpx.shape)
    xr_float = xx - dlpx
    xr = np.rint(xr_float).astype(np.int32)
    in_bounds = (xr_float >= 0) & (xr_float <= size[0]-1)
    xr_safe = np.clip(xr, 0, size[0]-1)
    opposite = drpx[yy, xr_safe]
    lr_error = np.abs(dlpx + opposite)
    valid = (supports[0] & in_bounds & supports[1][yy, xr_safe]
             & (dlpx > 0) & (dlpx < 255) & (opposite > -256) & (opposite < 0)
             & (lr_error <= 1.0))
    xyz = cv2.reprojectImageTo3D(dlpx, q)
    valid &= np.isfinite(xyz).all(axis=2) & (xyz[:, :, 2] > 0)
    depth = np.where(valid, xyz[:, :, 2], np.nan).astype(np.float32)
    assert valid.any(), 'No valid depth; do not render a fabricated result'
    assert np.all(depth[valid] > 0) and np.all(np.isnan(depth[~valid]))
    expected = pl[0, 0] * (-pr[0, 3]/pr[0, 0]) / dlpx[valid]
    assert np.allclose(depth[valid], expected, rtol=1e-5)

    # Independent target diagnostic: detect corners, resolve 180-degree labels,
    # measure epipolar residual and triangulate without refitting calibration.
    corners = []
    for im in (left, right):
        ok, pts = cv2.findChessboardCornersSB(im, (9, 6), cv2.CALIB_CB_NORMALIZE_IMAGE)
        corners.append(pts.astype(np.float64) if ok else None)
    board = dict(both_detected=all(p is not None for p in corners))
    board_mask = np.zeros(depth.shape, np.uint8)
    if board['both_detected']:
        cl, cr = [cv2.fisheye.undistortPoints(pts, k, d, R=r, P=p).reshape(-1, 2)
                  for pts, k, d, r, p in zip(corners, (kl, kr), (dl, dr), (rl, rr), (pl, pr))]
        if np.median(np.abs(cl[:, 1]-cr[::-1, 1])) < np.median(np.abs(cl[:, 1]-cr[:, 1])):
            cr = cr[::-1].copy()
        disparity = cl[:, 0]-cr[:, 0]
        cv2.fillConvexPoly(board_mask, cv2.convexHull(np.rint(cl).astype(np.int32)), 1)
        board_pixels = board_mask.astype(bool) & valid
        board.update(vertical_error_px=summary(np.abs(cl[:, 1]-cr[:, 1])),
                     corner_disparity_px=summary(disparity), positive_corner_disparity_fraction=float(np.mean(disparity > 0)),
                     sparse_corner_depth_m=summary(pl[0, 0]*(-pr[0, 3]/pr[0, 0])/disparity[disparity > 0]),
                     dense_depth_m=summary(depth[board_pixels]),
                     dense_valid_fraction=float(np.sum(board_pixels)/max(np.sum(board_mask), 1)),
                     note='Repeated checker pattern and textureless squares can cause mismatches; no metric ground truth.')

    OUT.mkdir(exist_ok=True)
    np.save(OUT / 'depth-m.npy', depth, allow_pickle=False)
    np.save(OUT / 'disparity-px.npy', dlpx, allow_pickle=False)
    write_image('valid-mask.png', valid.astype(np.uint8)*255)
    write_image('rectified-left.png', images[0])
    write_image('rectified-right.png', images[1])
    np.savez(OUT / 'rectification.npz', R_left=rl, R_right=rr, P_left=pl, P_right=pr, Q=q)
    # Linear distance color scale, warm near / cool far; color clipping only,
    # numeric data retain all valid positive depths, including outside this range.
    near, far = 0.2, 3.0
    normalized = np.clip((np.nan_to_num(depth, nan=far)-near)/(far-near), 0, 1)
    color = cv2.applyColorMap(np.rint((1-normalized)*255).astype(np.uint8), cv2.COLORMAP_TURBO)
    color[~valid] = 0
    write_image('depth-color.png', color)
    panel_w, panel_h = 544, 640
    canvas = np.full((810, 1192, 3), (27, 23, 20), np.uint8)
    for x, im, label in ((24, cv2.cvtColor(images[0], cv2.COLOR_GRAY2BGR), 'RECTIFIED LEFT'),
                         (592, color, 'STEREO DEPTH')):
        canvas[58:58+panel_h, x:x+panel_w] = cv2.resize(im, (panel_w, panel_h), interpolation=cv2.INTER_NEAREST)
        cv2.putText(canvas, label, (x, 36), cv2.FONT_HERSHEY_SIMPLEX, .65, (240, 240, 240), 1, cv2.LINE_AA)
    ramp = np.tile(np.linspace(255, 0, 840).astype(np.uint8), (16, 1))
    canvas[722:738, 180:1020] = cv2.applyColorMap(ramp, cv2.COLORMAP_TURBO)
    for text, xy in [('0.2 m / near', (24, 735)), ('3.0 m / far', (1032, 735)),
                     (f'Valid: {valid.mean()*100:.1f}% | Black = invalid | No hole filling', (24, 766)),
                     ('Candidate scale assumes 20 mm squares. Preview only; accuracy unverified.', (24, 795))]:
        cv2.putText(canvas, text, xy, cv2.FONT_HERSHEY_SIMPLEX, .48, (220, 220, 220), 1, cv2.LINE_AA)
    write_image('preview.png', canvas)
    readback = np.load(OUT / 'depth-m.npy', allow_pickle=False)
    assert np.array_equal(readback, depth, equal_nan=True)
    assert np.array_equal(cv2.imread(str(OUT / 'valid-mask.png'), 0) > 0, valid)
    assert before == {str(p): digest(p) for p in (SOURCE, CALIB)}
    report = dict(input_sha256=before, script_sha256=digest(Path(__file__)),
        opencv=cv2.__version__, numpy=np.__version__, source_kind='Previously decoded RTSP; not sensor RAW',
        geometry='Unmirror each half; physical left=cam1/right half, physical right=cam0/left half; invert cam0->cam1 extrinsics',
        image_size=list(size), output_reference='Rectified physical left (cam1); depth is optical-axis Z, not ray range',
        sgbm=settings, left_min_disparity=0, right_min_disparity=-255, lr_max_error_px=1.0,
        baseline_m=float(np.linalg.norm(translation)), rectified_focal_px=float(pl[0, 0]),
        valid_pixels=int(valid.sum()), valid_fraction=float(valid.mean()), depth_m=summary(depth[valid]),
        lr_error_px=summary(lr_error[valid]), board_diagnostic=board,
        quality_status='diagnostic_only_not_accepted_for_ranging',
        visual_assessment='Checkerboard depth is fragmented with apparent false matches; ceiling also contains suspect near-depth streaks.',
        color_scale_m=[near, far], color_clips_only=True, invalid_depth='NaN',
        input_hashes_unchanged=True, numeric_roundtrip_passed=True,
        calibration_modified=False, hardware_accessed=False, hole_filling=False,
        limitations=['20 mm physical checkerboard scale assumed', 'No distance ground truth or real-time performance test',
                    'Left-right consistency cannot exclude all repeated-pattern mismatches',
                    'Complete checkerboard not detected in both eyes; no corner-based geometry verification on this snapshot',
                    'Low-texture surfaces and occlusions remain invalid; decoded compression may affect matching'])
    (OUT / 'report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    (OUT / 'README.md').write_text('''# 雙目深度診斷預覽

`preview.png`：校正後實體左眼與深度對照。暖色近、冷色遠；黑色為無效，未補洞。
色尺為 0.2–3.0 m，超出範圍僅截斷顏色，不截斷數值。

`depth-m.npy`：float32，1088×1280（寬×高），公尺，無效為 NaN。
座標對齊 `rectified-left.png`，數值為校正後相機的光軸 Z，並非射線距離。
`valid-mask.png`：255 有效、0 無效。`disparity-px.npy`：原始浮點視差，
包含匹配器的無效值，使用時必須套用遮罩。`rectification.npz` 保存 R/P/Q。
`report.json` 記錄來源雜湊、參數、版本、有效比例及檢查結果。

目前品質：棋盤格有分段及疑似錯配，天花板亦有可疑近距離條紋。
左右一致性通過不等於真實深度正確；此圖不接受為測距結果。
兩眼未同時偵測到完整棋盤格，沒有本張影像的角點幾何驗證。
距離尺度依賴候選校正的 20 mm 方格假設，沒有距離真值驗證。

重現（在專案根目錄 PowerShell 執行，會覆寫此產出目錄內同名檔案）：

```powershell
outputs\\slam_benchmark\\depth-preview-venv\\Scripts\\python.exe outputs\\slam_benchmark\\generate-depth-preview.py
```

環境：Python 3.12、opencv-python-headless 5.0.0.93、numpy 2.5.4。
程式只讀取既有快照與校正，不存取板端或串流，不重新擬合參數。
''', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
