import csv
import hashlib
import json
from pathlib import Path
import shutil

import cv2
import numpy as np

base = Path(__file__).resolve().parent
root = base / 'stereo-validation-rtsp-wide-20261014'
session = base / 'live-calibration-20261013/target-rtsp-wide-20261014'

def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

report = load(root / 'evaluation/report.json')
capture = load(root / 'transaction.json')
inspection = load(session / 'target-coverage/report.json')
assert capture['status'] == 'completed' and capture['saved_pairs'] == 296
assert capture['candidate_unchanged'] and report['candidate_unchanged']
assert not capture['RTSP_server_paused'] and not capture['sensor_controls_modified']
assert digest(root / 'frozen-candidate.npz') == '819d0befaabe1973d299107b0a181e6ec93853a641840e3c9da04e1c84d4732b'
after = load(root / 'board-after.json')
assert 'ActiveState=active' in after['service']['stdout']
assert after['files']['/var/lib/sc132gs-camera/settings.yaml']['sha256'] == '602bd5f039e2550ebf3262a502df9cf4708b917aad798e084d4b819e1d4ccd74'
rows = list(csv.DictReader((session / 'camera-frames.csv').open()))
assert len(rows) == 592 and set(row['eye'] for row in rows) == {'0', '1'}
assert 'stream_pts_ns' in rows[0] and 'receiver_timestamp_ns' not in rows[0]
image_hashes = {}
for row in rows:
    path = session / row['image']
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    assert image is not None and image.shape == (1280, 1088)
    image_hashes[row['image']] = digest(path)
save(session / 'images-sha256.json', image_hashes)

# Preserve the earlier RTSP CSV byte-for-byte before clarifying its misleading legacy header.
legacy = base / 'live-calibration-20261013/target-rtsp-redo-20261014/camera-frames.csv'
if legacy.exists() and not legacy.with_name('camera-frames-original-header.csv').exists():
    shutil.copyfile(legacy, legacy.with_name('camera-frames-original-header.csv'))
    old_text = legacy.read_text()
    old_text = old_text.replace('sequence,flags,receiver_timestamp_ns,dequeue_timestamp_ns',
                    'decoded_sequence,unused_flags,stream_pts_ns,windows_receive_monotonic_ns', 1)
    legacy.write_text(old_text, encoding='utf-8')

sources = root / 'tested-analysis'
sources.mkdir(exist_ok=True)
for name in ['inspect-target-session.py', 'evaluate-independent-stereo.py', 'finalize-rtsp-validation.py']:
    shutil.copyfile(base / name, sources / name)
shutil.copytree(base / 'stereo-validation-rtsp-redo-20261014/deployed-source', root / 'deployed-source', dirs_exist_ok=True)

models = report['metrics']
parameters = np.load(root / 'frozen-candidate.npz')
K = [parameters[f'K{eye}'] for eye in (0, 1)]
D = [parameters[f'D{eye}'] for eye in (0, 1)]
R = parameters['R_cam1_cam0']
T = parameters['T_cam1_cam0_m_assuming_20mm_squares']
chosen = next(item for item in inspection['observations'] if item['both_found'])
pair = [row for row in rows if int(row['pair_id']) == chosen['pair_id']]
images = [cv2.imread(str(session / next(row['image'] for row in pair if int(row['eye']) == eye)), cv2.IMREAD_GRAYSCALE) for eye in (0, 1)]
r0, r1, p0, p1, _ = cv2.fisheye.stereoRectify(K[0], D[0], K[1], D[1], (1088, 1280), R, T,
    flags=cv2.CALIB_ZERO_DISPARITY, newImageSize=(1088, 1280), balance=0.0)
rectified = []
for eye in (0, 1):
    maps = cv2.fisheye.initUndistortRectifyMap(K[eye], D[eye], [r0,r1][eye], [p0,p1][eye], (1088,1280), cv2.CV_32FC1)
    rectified.append(cv2.remap(images[eye], *maps, cv2.INTER_LINEAR))
preview = cv2.cvtColor(cv2.resize(np.hstack(rectified), None, fx=.5, fy=.5), cv2.COLOR_GRAY2BGR)
for y in range(32, preview.shape[0], 32):
    cv2.line(preview, (0,y), (preview.shape[1]-1,y), (0,190,255), 1)
cv2.putText(preview, 'Independent RTSP decode; frozen candidate; mirror undone', (10,23), cv2.FONT_HERSHEY_SIMPLEX, .5, (0,255,255), 1)
assert cv2.imwrite(str(root / 'candidate-preview.png'), preview)

verification = dict(status='independent_RTSP_validation_completed_full_field_not_accepted',
    session=capture['session'], input_source=report['input_source'],
    source_processing='HEVC Main10 -> RGB -> mono8 -> split eyes -> undo horizontal mirror per eye',
    source_eye_order='cam0/right sensor0x32 in displayed left half; cam1/left sensor0x30 in displayed right half',
    source_geometry_verified_from_deployed_CPP=True,
    saved_pairs=296, verified_PNG_images=len(image_hashes), complete_sampled_pairs=57, sampled_pairs=60,
    frozen_candidate_sha256=digest(root / 'frozen-candidate.npz'), refit_performed=False,
    full_field_diagnostic_gate_passed=False, RAW_sensor_calibration_accepted=False,
    camera_IMU_calibration_complete=False, RTSP_continued_during_capture=True,
    RTSP_active_after_evaluation=True, saved_settings_unchanged=True,
    previous_attempts=dict(RAW_session='target-validation-20261014, retained on board; inspection superseded at user redo request',
                           first_RTSP_session='target-rtsp-redo-20261014, 297 pairs retained; 4/60 complete'),
    metrics=models, coverage=report['coverage'],
    next_step='Keep preview available; obtain original-image export from the camera owner for a RAW comparison, then resolve remaining upper-field coverage and error before accepting camera geometry.')
save(root / 'verification.json', verification)

comparison = ''
for title, name in [('出廠外參', 'factory'), ('固定候選外參', 'frozen_candidate')]:
    m = models[name]['vertical_error']
    norm = models[name]['vertical_error_at_common_650px_focal']
    comparison += f'<tr><td>{title}</td><td>{m["median_px"]:.3f}</td><td>{m["p95_px"]:.3f}</td><td>{m["max_px"]:.3f}</td><td>{norm["p95_px"]:.3f}</td></tr>'
coverage_tables = ''
for item in report['coverage']:
    body = ''.join('<tr><th>'+label+'</th>'+''.join(f'<td>{value}</td>' for value in values)+'</tr>'
                   for label, values in zip(['上','中','下'], item['center_grid_3x3']))
    coverage_tables += f'<div><h3>cam{item["eye"]}：角點聯集 {item["corner_hull_image_fraction"]*100:.1f}%</h3><table><tr><th>棋盤中心</th><th>左</th><th>中</th><th>右</th></tr>{body}</table></div>'
document = f'''<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>第二輪 RTSP 獨立驗證</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f0f4f8;color:#192f43;font:16px/1.75 system-ui,sans-serif}}main{{max-width:1160px;margin:auto;padding:30px 22px 60px}}h1{{font-size:28px;line-height:1.4}}h2{{font-size:21px}}h3{{font-size:17px}}.card{{background:white;padding:22px;margin:20px 0;border:1px solid #d7e1eb;border-radius:12px}}.notice{{padding:14px 18px;background:#fff0d8;border-left:4px solid #bf7e17}}.muted{{color:#54697b}}table{{width:100%;border-collapse:collapse}}th,td{{padding:10px;border-bottom:1px solid #dce4ed;text-align:left}}th{{background:#edf3f8}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}img{{width:100%;height:auto}}code{{background:#e7eef5;padding:3px 6px}}a{{color:#0766a2}}.scroll{{overflow:auto}}@media(max-width:760px){{main{{padding:18px 12px}}.grid{{grid-template-columns:1fr}}}}
</style></head><body><main><div class="muted">2026-10-14 · RUBIK Pi 3 / GS130WI</div><h1>第二輪獨立驗證完成，RTSP 全程保持預覽</h1>
<div class="notice">本輪為 HEVC 解碼影像驗證，已還原左右鏡像。候選參數維持原值；目前全視野診斷未通過，未部署候選，也未宣告 RAW 或相機–IMU 標定完成。</div>
<section class="card"><h2>採集結果</h2><p>60.02 秒串流 PTS、約 60.03 秒本機記錄；共保存 296 組、592 張 PNG。抽查 60 組，有 57 組兩眼都找到完整 54 角點；比前次重拍的 4／60 組改善。RTSP 未停止，感測器設定未修改。</p><p>預覽網址：<code>rtsp://192.168.137.226:8554/stereo</code></p></section>
<section class="card"><h2>固定模型的新資料檢查</h2><p>全部 57 組完整棋盤、3,078 個角點均納入，沒有按誤差刪點，也沒有重新求解 K、D、R、T。</p><div class="scroll"><table><tr><th>模型</th><th>上下偏差中位數 px</th><th>P95 px</th><th>最大 px</th><th>650 px 統一焦距 P95</th></tr>{comparison}</table></div><p class="muted">前四欄在 1088×1280 校正影像計算；候選虛擬焦距約 487.66 px，出廠約 486.00 px。統一焦距欄避免以不同縮放混比。第一輪 0.24 px 是同一 RAW 採集的保留姿態，與本輪壓縮串流、不同位置的結果證據範圍不同。</p><p>候選在本輪仍較出廠外參改善，但 P95 約 1.03 px，統一焦距後約 1.38 px，尚未達本專案採用的 1 px 診斷目標。這個門檻不是外部標準或產品認證。</p></section>
<section class="card"><h2>視野覆蓋與缺口</h2><p>角點聯集由第一輪約 17%～19% 提高至約 42%；棋盤中心仍未進入影像上方三分之一。下表數值是各區域的完整棋盤中心觀測數。</p><div class="grid">{coverage_tables}</div><p>本輪增加了可用區域，但不足以宣告全視野校正精度。少數角點也有較大殘差，已原樣保留。</p></section>
<section class="card"><h2>固定候選的校正預覽</h2><p>左半 cam0／右眼，右半 cam1／左眼。黃色線標記相同影像列。</p><img src="candidate-preview.png" alt="鏡像還原後，套用固定候選參數的 RTSP 驗證影像"></section>
<section class="card"><h2>資料範圍與下一步</h2><p>串流經 HEVC 有損壓縮，Main10 解碼後轉成 mono8 保存，可能影響角點位置；目前不能把殘差完全歸因於標定。時間欄位保留為串流 PTS 與 Windows 接收時刻，沒有冒充相機曝光或 IMU 時間。</p><p>下一步在保持預覽的流程中取得原始影像對照，再處理剩餘上方視野與誤差。相機–IMU 共同時間、外參與雜訊模型仍是後續階段。</p><p><a href="evaluation/report.json">完整數值與逐姿態結果</a> · <a href="evaluation/corner-errors.csv">逐角點誤差</a> · <a href="verification.json">驗證範圍</a> · <a href="../live-calibration-20261013/target-rtsp-wide-20261014/images-sha256.json">592 張影像雜湊</a></p></section></main></body></html>'''
(root / 'report.html').write_text(document, encoding='utf-8')
status = load(base / 'openvins-status.json')
status['independent_camera_validation'] = verification
status['independent_camera_validation']['report'] = 'stereo-validation-rtsp-wide-20261014/report.html'
status['next_step'] = verification['next_step']
save(base / 'openvins-status.json', status)
save(root / 'evidence-sha256.json', {str(path.relative_to(root)).replace('\\','/'):digest(path)
     for path in root.rglob('*') if path.is_file() and path.name != 'evidence-sha256.json'})
print(json.dumps(dict(images_verified=592, complete_sampled_pairs=57, candidate_unchanged=True,
                     RTSP_active=True, full_field_accepted=False, report=str(root / 'report.html'))))
