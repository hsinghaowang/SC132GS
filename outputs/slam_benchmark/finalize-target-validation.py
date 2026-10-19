"""Finalize a named preview-preserving capture without changing camera geometry."""
import argparse
import csv
import hashlib
import html
import json
from pathlib import Path
import re
import shutil

import cv2
import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument('--session', required=True)
args = parser.parse_args()
base = Path(__file__).resolve().parent
session = base / 'live-calibration-20261013' / args.session
root = base / ('stereo-validation-' + args.session.removeprefix('target-'))
baseline_root = base / 'stereo-validation-rtsp-wide-20261014'


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def board_state(path):
    raw = path.read_text(encoding='utf-8-sig')
    properties = dict(re.findall(r'^(MainPID|ActiveState|SubState|ActiveEnterTimestamp)=(.*)$', raw, re.M))
    hashes = {p.strip(): h for h, p in re.findall(r'^([0-9a-f]{64})\s+(/[^\r\n]+)$', raw, re.M)}
    return properties, hashes


capture = load(root / 'transaction.json')
report = load(root / 'evaluation/report.json')
inspection = load(session / 'target-coverage/report.json')
baseline = load(baseline_root / 'evaluation/report.json')
assert capture['status'] == 'completed'
assert capture['candidate_unchanged'] and report['candidate_unchanged']
assert not capture['RTSP_server_paused'] and not capture['sensor_controls_modified']
assert not report['parameter_optimization_or_refit_performed']
assert digest(root / 'frozen-candidate.npz') == capture['frozen_candidate_sha256']
assert digest(root / 'frozen-candidate.npz') == digest(base / 'calibration-ready-20261014/geometry-analysis/stereo-candidate.npz')
before, before_hashes = board_state(root / 'board-state-during-capture.txt')
after, after_hashes = board_state(root / 'board-state-after.txt')
assert before['ActiveState'] == after['ActiveState'] == 'active'
assert before['MainPID'] == after['MainPID']
assert before['ActiveEnterTimestamp'] == after['ActiveEnterTimestamp']
assert before_hashes == after_hashes and len(after_hashes) == 3

rows = list(csv.DictReader((session / 'camera-frames.csv').open(newline='')))
assert len(rows) == capture['saved_pairs'] * 2
assert 'stream_pts_ns' in rows[0] and 'windows_receive_monotonic_ns' in rows[0]
image_hashes = {}
pairs = {}
for row in rows:
    path = session / row['image']
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    assert image is not None and image.shape == (1280, 1088)
    assert row['image'] not in image_hashes
    image_hashes[row['image']] = digest(path)
    pairs.setdefault(int(row['pair_id']), set()).add(int(row['eye']))
assert all(eyes == {0, 1} for eyes in pairs.values())
save(session / 'images-sha256.json', image_hashes)

analysis = root / 'tested-analysis'
analysis.mkdir(exist_ok=True)
for name in ['inspect-target-session.py', 'evaluate-independent-stereo.py', 'finalize-target-validation.py']:
    shutil.copyfile(base / name, analysis / name)

complete = [item for item in inspection['observations'] if item['both_found']]
highest = min(complete, key=lambda item: max(eye['center_normalized'][1] for eye in item['eyes']))
shutil.copyfile(session / f'target-coverage/pair-{highest["pair_id"]}.png', root / 'upper-target-preview.png')
worst = max(report['observations'], key=lambda item: item['models']['frozen_candidate']['vertical_error']['max_px'])
shutil.copyfile(session / f'target-coverage/pair-{worst["pair_id"]}.png', root / 'largest-residual-preview.png')

baseline_session = base / 'live-calibration-20261013/target-rtsp-wide-20261014'
baseline_inspection = load(baseline_session / 'target-coverage/report.json')
assert digest(baseline_root / 'frozen-candidate.npz') == capture['frozen_candidate_sha256']
union_observations = complete + [item for item in baseline_inspection['observations'] if item['both_found']]
union_coverage = []
for eye in (0, 1):
    points = np.concatenate([np.array(item['eyes'][eye]['corners'], dtype=np.float32) for item in union_observations])
    centers = np.array([item['eyes'][eye]['center_normalized'] for item in union_observations])
    grid = np.zeros((3, 3), dtype=int)
    for x, y in centers:
        grid[min(2, int(y * 3)), min(2, int(x * 3))] += 1
    union_coverage.append(dict(eye=eye,
        corner_hull_image_fraction=float(cv2.contourArea(cv2.convexHull(points)) / (1088 * 1280)),
        center_min=centers.min(axis=0).tolist(), center_max=centers.max(axis=0).tolist(),
        center_span=np.ptp(centers, axis=0).tolist(), center_grid_3x3=grid.tolist()))
union_coverage_passed = all(item['corner_hull_image_fraction'] >= .6 and min(item['center_span']) >= .45 for item in union_coverage)
union = dict(source_sessions=['target-rtsp-wide-20261014', args.session], complete_pairs=len(union_observations),
    source_inspection_sha256=[digest(baseline_session / 'target-coverage/report.json'), digest(session / 'target-coverage/report.json')],
    source_models_identical=True, frozen_candidate_sha256=capture['frozen_candidate_sha256'],
    geometry_fitting_performed=False, coverage=union_coverage,
    project_specific_coverage_gate_passed=union_coverage_passed,
    accuracy_acceptance=False,
    limitation='Coverage union only. Prior session: 60 FPS/20 Mbit/s; current: 30 FPS/10 Mbit/s. Residuals and capture provenance remain separate.')
save(root / 'coverage-union.json', union)

current_errors = []
with (root / 'evaluation/corner-errors.csv').open(newline='') as stream:
    for row in csv.DictReader(stream):
        if row['model'] == 'frozen_candidate':
            current_errors.append(float(row['vertical_error_px']))
outliers = dict(native_virtual_focal_px=report['metrics']['frozen_candidate']['virtual_focal_px'],
    corner_count=len(current_errors), count_above_1px=sum(value > 1 for value in current_errors),
    count_above_3px=sum(value > 3 for value in current_errors),
    count_above_5px=sum(value > 5 for value in current_errors),
    maximum_px=max(current_errors), largest_error_pair=worst['pair_id'],
    residual_based_rejection_performed=False)
save(root / 'large-residual-diagnostics.json', outliers)

comparison = []
for eye in (0, 1):
    previous = baseline['coverage'][eye]
    current = report['coverage'][eye]
    comparison.append(dict(eye=eye,
        previous_upper_center_observations=sum(previous['center_grid_3x3'][0]),
        current_upper_center_observations=sum(current['center_grid_3x3'][0]),
        previous_corner_hull_fraction=previous['corner_hull_image_fraction'],
        current_corner_hull_fraction=current['corner_hull_image_fraction'],
        current_center_grid_3x3=current['center_grid_3x3']))
verified_fps = (capture['decoded_frames'] - 1) / capture['pts_duration_seconds']
verification = dict(status='independent_RTSP_diagnostic_completed', session=args.session,
    input_source=report['input_source'], source_processing='HEVC Main10 -> RGB -> mono8 -> split eyes -> undo horizontal mirror per eye',
    source_eye_order='cam0/right sensor0x32 in displayed left half; cam1/left sensor0x30 in displayed right half',
    saved_pairs=capture['saved_pairs'], verified_PNG_images=len(image_hashes),
    complete_sampled_pairs=report['complete_target_pairs'], sampled_pairs=report['sampled_pairs'],
    frozen_candidate_sha256=capture['frozen_candidate_sha256'], refit_performed=False, candidate_deployed=False,
    full_field_diagnostic_gate_passed=report['full_field_diagnostic_gate_passed'],
    coverage_gate_passed=report['coverage_gate_passed'], epipolar_error_gate_passed=report['epipolar_error_gate_passed'],
    RAW_sensor_calibration_accepted=False, camera_IMU_calibration_complete=False,
    RTSP_continued_during_capture=True, RTSP_active_after_evaluation=True,
    camera_owner_PID_and_start_time_unchanged=True, saved_settings_and_owner_scripts_unchanged=True,
    decoded_pts_fps=verified_fps, board_state_hashes=after_hashes,
    metrics=report['metrics'], coverage=report['coverage'], comparison_to_previous=comparison,
    complementary_coverage_union=union, large_residual_diagnostics=outliers,
    previous_report='stereo-validation-rtsp-wide-20261014/report.html',
    next_step='Review independent RTSP coverage and residuals; preserve preview and frozen geometry. RAW comparison and camera-IMU timing/extrinsics remain pending.',
    report=str(root.relative_to(base) / 'report.html').replace('\\', '/'))
save(root / 'verification.json', verification)

coverage_tables = ''
for entry in report['coverage']:
    body = ''.join('<tr><th>' + label + '</th>' + ''.join(f'<td>{count}</td>' for count in values) + '</tr>'
                   for label, values in zip(['上', '中', '下'], entry['center_grid_3x3']))
    coverage_tables += f'<div><h3>cam{entry["eye"]}：角點凸包 {entry["corner_hull_image_fraction"]*100:.1f}%</h3><table><tr><th>棋盤中心</th><th>左</th><th>中</th><th>右</th></tr>{body}</table></div>'
metric_rows = ''
for label, name in [('出廠外參', 'factory'), ('固定候選外參', 'frozen_candidate')]:
    values = report['metrics'][name]['vertical_error']
    common = report['metrics'][name]['vertical_error_at_common_650px_focal']
    metric_rows += f'<tr><td>{label}</td><td>{values["median_px"]:.3f}</td><td>{values["p95_px"]:.3f}</td><td>{values["max_px"]:.3f}</td><td>{common["p95_px"]:.3f}</td></tr>'
prior_rows = ''.join(f'<tr><td>cam{item["eye"]}</td><td>{item["previous_upper_center_observations"]}</td><td>{item["current_upper_center_observations"]}</td><td>{item["previous_corner_hull_fraction"]*100:.1f}%</td><td>{item["current_corner_hull_fraction"]*100:.1f}%</td><td>{union_coverage[item["eye"]]["corner_hull_image_fraction"]*100:.1f}%</td></tr>' for item in comparison)
coverage_result = '通過' if report['coverage_gate_passed'] else '未通過'
error_result = '通過' if report['epipolar_error_gate_passed'] else '未通過'
union_result = '通過' if union_coverage_passed else '未通過'
document = f'''<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>上方與周邊補拍驗證</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f0f4f8;color:#192f43;font:16px/1.75 system-ui,sans-serif}}main{{max-width:1100px;margin:auto;padding:28px 20px 50px}}h1{{font-size:28px}}h2{{font-size:21px}}h3{{font-size:17px}}section{{background:white;padding:20px;margin:18px 0;border:1px solid #d7e1eb;border-radius:10px}}.notice{{padding:14px 18px;background:#fff0d8;border-left:4px solid #bf7e17}}table{{width:100%;border-collapse:collapse}}th,td{{padding:9px;border-bottom:1px solid #dce4ed;text-align:left}}th{{background:#edf3f8}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}img{{width:100%;height:auto}}a{{color:#0766a2}}.scroll{{overflow:auto}}@media(max-width:650px){{main{{padding:16px 12px}}.grid{{grid-template-columns:1fr}}}}
</style></head><body><main><h1>上方與周邊補拍：固定模型獨立驗證</h1>
<div class="notice">兩輪聯合覆蓋診斷：{union_result}；本輪誤差診斷：{error_result}，但仍有大誤差角點。本輪是 RTSP 壓縮解碼資料，並非 RAW 精度驗收；未重新求解或部署標定參數。</div>
<section><h2>採集與預覽</h2><p>串流 PTS {capture['pts_duration_seconds']:.2f} 秒，保存 {capture['saved_pairs']} 組、{len(image_hashes)} 張影像。抽樣 {report['sampled_pairs']} 組，{report['complete_target_pairs']} 組雙眼完整 54 角點。解碼 PTS 頻率 {verified_fps:.2f} FPS。</p><p>相機 owner PID 與啟動時間、設定及 owner scripts 雜湊前後相同。預覽保持運行；串流設定 30 FPS、目標 10 Mbit/s。</p></section>
<section><h2>本輪棋盤中心分布</h2><div class="grid">{coverage_tables}</div><p>凸包比例表示已觀測角點的包圍區域；不能把它當成每個像素都已驗證。各區數字只計完整雙眼棋盤的中心位置。</p></section>
<section><h2>與上一輪對照及聯合覆蓋</h2><div class="scroll"><table><tr><th>眼別</th><th>前輪上方中心數</th><th>本輪上方中心數</th><th>前輪凸包</th><th>本輪凸包</th><th>聯合凸包</th></tr>{prior_rows}</table></div><p>前輪偏下方，本輪補上方；共 {len(union_observations)} 組完整棋盤的聯合覆蓋通過專案覆蓋門檻。本輪單獨覆蓋診斷：{coverage_result}。兩輪抽樣數、姿態及串流設定不同：前輪 60 FPS／20 Mbit/s，本輪 30 FPS／10 Mbit/s。聯合僅統計位置覆蓋，誤差與採集來源分開保留，沒有合併成一次新的採集或精度驗收。</p></section>
<section><h2>未修改模型的殘差</h2><div class="scroll"><table><tr><th>模型</th><th>中位數 px</th><th>P95 px</th><th>最大 px</th><th>統一650px焦距 P95</th></tr>{metric_rows}</table></div><p>全部完整棋盤納入，沒有根據殘差刪點。每張圖只估算棋盤姿態作診斷；K、D、雙目 R、T 均固定。覆蓋與誤差門檻是專案診斷規則，不是外部標準或產品認證。</p></section>
<section><h2>最上方完整棋盤觀測</h2><img src="upper-target-preview.png" alt="兩眼已還原水平鏡像；本輪完整棋盤中位置最高的一組角點檢查"></section>
<section><h2>保留的大誤差</h2><p>候選 {len(current_errors)} 個角點中，{outliers['count_above_3px']} 個上下偏差大於 3 px，{outliers['count_above_5px']} 個大於 5 px；最大 {outliers['maximum_px']:.2f} px，出現在 pair {worst['pair_id']}。這些點全部保留。單眼棋盤姿態重投影也有局部大誤差，角點定位、影像品質與模型皆需進一步對照；目前不能把原因歸於其中一項。</p><img src="largest-residual-preview.png" alt="本輪最大候選上下偏差所在影像，所有角點保留"></section>
<section><h2>證據範圍</h2><p>HEVC Main10 解碼後經 RGB 轉 mono8、分割雙目並還原水平鏡像。有損壓縮、曝光與移動可能影響角點殘差。時間欄是串流 PTS 與 Windows 接收時刻，並非曝光或 IMU 取樣時刻。RAW 對照、相機–IMU 時間、外參及雜訊模型仍待完成。</p><p><a href="evaluation/report.json">完整數值</a> · <a href="evaluation/corner-errors.csv">逐角點誤差</a> · <a href="coverage-union.json">聯合覆蓋證據</a> · <a href="verification.json">驗證範圍</a> · <a href="../{html.escape(str(session.relative_to(base)).replace(chr(92), '/'))}/images-sha256.json">影像雜湊</a></p></section></main></body></html>'''
(root / 'report.html').write_text(document, encoding='utf-8')
status = load(base / 'openvins-status.json')
shutil.copyfile(base / 'openvins-status.json', root / 'status-before-finalization.json')
status['independent_camera_validation'] = verification
status['next_step'] = verification['next_step']
save(base / 'openvins-status.json', status)
save(root / 'evidence-sha256.json', {str(path.relative_to(root)).replace('\\', '/'): digest(path)
     for path in root.rglob('*') if path.is_file() and path.name != 'evidence-sha256.json'})
print(json.dumps(dict(saved_pairs=capture['saved_pairs'], complete_sampled_pairs=report['complete_target_pairs'],
    sampled_pairs=report['sampled_pairs'], decoded_pts_fps=verified_fps,
    comparison=comparison, coverage_gate_passed=report['coverage_gate_passed'],
    union_coverage=union_coverage, union_coverage_gate_passed=union_coverage_passed, large_residuals=outliers,
    epipolar_error_gate_passed=report['epipolar_error_gate_passed'],
    full_field_accepted=False, report=str(root / 'report.html')), ensure_ascii=False))
