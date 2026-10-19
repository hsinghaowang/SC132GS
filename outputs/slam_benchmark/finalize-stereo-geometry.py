import hashlib
import html
import json
from pathlib import Path
import shutil

root = Path(__file__).resolve().parent
output = root / 'factory-geometry-full-20261013'


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


report = load(output / 'report.json')
first = load(root / 'factory-geometry-20261013/report.json')
pose = load(output / 'pose-sign-check.json')
after = load(root / 'factory-geometry-board-after.json')
previous = load(root / 'factory-calibration-20261013/after.json')
same_state = after['files'] == previous['files'] and after['service']['stdout'] == previous['service']['stdout']
assert same_state, 'Camera saved state differs from EEPROM baseline; inspect instead of claiming preserved'
assert 'ActiveState=inactive' in after['service']['stdout']
raw_verified = 0
for evidence_folder in [root / 'factory-geometry-20261013', output]:
    for relative, expected in load(evidence_folder / 'input-sha256.json').items():
        assert digest(root / relative) == expected, relative
        raw_verified += 1
shutil.copyfile(root / 'factory-geometry-board-after.json', output / 'board-after.json')
for source_name in ['check-factory-stereo.py', 'check-stereo-pose-sign.py']:
    shutil.copyfile(root / source_name, output / source_name)

primary = report['controls']['factory']['all_appearance_matches']
secondary = report['controls']['factory']['independently_fitted_F_subset']
direction = pose['runs']['factory-geometry-full-20261013']
positive = direction['documented_factory_inverse']['all_appearance_matches']['positive_depth_fraction']
negative_control_positive = direction['alternative_direction_control']['all_appearance_matches']['positive_depth_fraction']
verification = dict(status='diagnostic_completed_accuracy_not_accepted',
    physical_saved_camera_images=True, sampled_pairs_initial=first['sampled_pairs'],
    sampled_pairs_full_resolution=report['sampled_pairs'],
    unique_viewpoints='One mostly stationary scene; repetitions are not independent coverage',
    factory_extrinsics_modified=False, live_VIO_performed=False,
    complete_checkerboard_pairs=report['complete_checkerboard_pairs'],
    all_appearance_matches=primary, independently_fitted_F_subset=secondary,
    raw_input_hash_checks=raw_verified,
    saved_camera_state_matches_EEPROM_baseline=same_state, camera_service_inactive=True,
    documented_direction_positive_depth_fraction=positive,
    alternative_direction_positive_depth_fraction=negative_control_positive,
    conclusions=[
        'Factory transform direction is compatible with point-in-front checks on this scene.',
        'Residual epipolar misalignment remains after full-resolution appearance refinement.',
        'Do not substitute inverse-direction control simply because its vertical residual is smaller.',
        'No reprojection accuracy, metric baseline, physical exposure synchronization or camera-IMU calibration claim.',
    ],
    next_step='Prepare the 20mm target for varied stereo poses; validate factory geometry before deciding whether recalibration is required.')
save(output / 'verification.json', verification)

rows = ''
for label, item in [('所有外觀匹配', primary), ('獨立幾何模型篩選子集', secondary)]:
    rows += f'<tr><td>{label}</td><td>{item["count"]}</td><td>{item["median_px"]:.3f}</td><td>{item["p95_px"]:.3f}</td><td>{item["fraction_le_1px"]*100:.1f}%</td></tr>'
source = 'https://github.com/D-Robotics/gs130_camera_sdk/blob/12bde1f530533a11eba1803c1de525cee928c88b/core/src/devices/eeprom/union_stereo_imu_fisheye_v1p2r0n4.cpp'
doc = 'https://docs.opencv.org/4.5.4/db/d58/group__calib3d__fisheye.html'
document = f'''<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SC132GS 出廠參數：現有影像幾何檢查</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#f1f4f8;color:#182b40;font:16px/1.7 system-ui,sans-serif}}
main{{max-width:1180px;margin:auto;padding:32px 22px 60px}}h1{{font-size:30px;line-height:1.35;margin:8px 0 18px}}
h2{{font-size:21px}}.card{{background:white;border:1px solid #d8e0e8;border-radius:12px;padding:22px;margin:20px 0}}
.status{{color:#874b00;background:#fff1da;padding:12px 16px;border-left:4px solid #c47d12;border-radius:4px}}
.muted{{color:#536579}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;padding:12px 10px;border-bottom:1px solid #dce3e9}}th{{background:#edf3f8}}
img{{width:100%;height:auto;background:#111;border-radius:6px}}a{{color:#0064a5}}code{{font-size:14px;background:#edf2f7;padding:2px 5px}}details{{margin-top:16px}}
.columns{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}@media(max-width:780px){{.columns{{grid-template-columns:1fr}}main{{padding:20px 12px}}h1{{font-size:25px}}.table-wrap{{overflow:auto}}}}
</style></head><body><main>
<div class="muted">RUBIK Pi 3 · SC132GS / GS130WI · 2026-10-13</div>
<h1>現有實體影像檢查完成；幾何精度仍待標定板驗證</h1>
<div class="status">出廠內參可以完成魚眼去畸變與雙目校正，但仍存在上下偏差。目前不將這組參數標記為幾何驗證通過。</div>
<section class="card"><h2>完整解析度核對結果</h2>
<p>先抽查 50 組已存影像中的 10 組，再以完整解析度檢查開始、中間及結尾共 3 組。223 個匹配經外觀與雙向追蹤選擇，未用出廠極線誤差篩掉失敗點。影像為同一個大致靜止場景，沒有標定板，也不代表多視角精度驗證。</p>
<div class="table-wrap"><table><thead><tr><th>匹配集合</th><th>匹配數</th><th>上下偏差中位數／px</th><th>P95／px</th><th>≤1 px</th></tr></thead><tbody>{rows}</tbody></table></div>
<p class="muted">偏差以 1088×1280 校正影像計算，虛擬焦距約 486 px。第二列以獨立擬合的基本矩陣篩選誤配，會改變樣本集合，所以也保留第一列全部外觀匹配結果。兩列均未達到可直接宣告精度通過的證據。</p></section>
<section class="card"><h2>方向與平移符號</h2>
<p>官方 EEPROM 格式以右眼為參考：<code>p_right = R × p_left + T</code>。目前 cam0 為右眼、cam1 為左眼，因此雙目工具使用反矩陣：</p>
<p><code>R_cam1_cam0 = Rᵀ</code>；<code>T_cam1_cam0 = −RᵀT</code>。</p>
<p>按此方向計算，<strong>{positive*100:.1f}%</strong> 的外觀匹配點在兩眼前方；直接使用另一方向只有 <strong>{negative_control_positive*100:.1f}%</strong>。另一方向雖然上下偏差稍低，卻使大部分三角化點落在相機後方，不能以較低偏差為由採用。</p>
<p class="muted">此檢查支持目前方向與符號，並不證明所有外參正確。平移原始向量長度為 {report['factory_translation_norm_raw']:.9f}，尺度單位尚未獨立確認；本報告不把它宣告為實測基線或深度精度。</p></section>
<section class="card"><h2>相同實體影像的校正預覽</h2>
<p>兩張圖的左半為 cam0／右眼，右半為 cam1／左眼。黃色線為相同影像列，方便觀察對應物件的上下位置；畫面沒有用影像擬合結果重新調整出廠外參。</p>
<details><summary>查看校正前</summary><img src="raw-pair.png" alt="已存實體影像的雙目原始影像，黃線標記相同影像列"></details>
<p>魚眼與雙目校正後：</p><img src="rectified-pair.png" alt="使用出廠參數校正後的雙目影像，黃線標記相同影像列">
</section>
<section class="card"><h2>接下來需要的證據</h2>
<p>先準備已提供的 20 mm 棋盤板，以不同位置、距離和傾角入鏡，涵蓋中心到四周。用已知角點檢查每眼重投影誤差及雙目一致性，再決定保留或重新求解出廠參數。相機–IMU 外參、共同時間、曝光同步與 IMU 雜訊模型仍待另行驗證。</p>
<p>本輪只讀既有檔案。相機持久設定與 runtime state 雜湊核對一致，串流仍為原本停止狀態；没有改寫 EEPROM 或出廠參數。</p>
<p><a href="report.json">數值報告</a> · <a href="appearance-matches.csv">全部外觀匹配</a> · <a href="pose-sign-check.json">方向對照</a> · <a href="verification.json">驗證範圍</a></p>
<details><summary>方法與官方來源</summary><p>OpenCV {html.escape(report['opencv_version'])}；完整解析度 SIFT 雙向 ratio0.75；21×21 LK 雙向追蹤，回程誤差≤0.5 px、初始位置修正≤3 px。獨立基本矩陣 RANSAC 門檻1 px，與出廠外參無關。相同曝光時刻及米制基線未由此檢查建立。</p><p><a href="{source}">官方 EEPROM 模型與座標方向</a> · <a href="{doc}">OpenCV 魚眼校正定義</a></p></details>
</section></main></body></html>'''
(output / 'report.html').write_text(document, encoding='utf-8')

status_path = root / 'openvins-status.json'
status = load(status_path)
status['factory_calibration']['geometry_diagnostic'] = {
    'status': verification['status'], 'report': 'factory-geometry-full-20261013/report.html',
    'sampled_pairs_initial': 10, 'sampled_pairs_full_resolution': 3,
    'appearance_matches': primary, 'independently_fitted_F_subset': secondary,
    'positive_depth_fraction': positive,
    'factory_intrinsics_or_extrinsics_modified': False,
    'camera_saved_state_preserved': same_state,
    'geometric_accuracy_accepted': False,
}
status['next_step'] = 'User has not prepared the physical target. Existing-image checks completed with residual epipolar error; next prepare the 20mm board for varied stereo target observations, then verify/recalibrate geometry and camera-IMU timing before live VIO.'
status['physical_calibration_preparation']['next_step'] = status['next_step']
save(status_path, status)

source_manifest = {str(path.relative_to(output)).replace('\\', '/'): digest(path)
                   for path in sorted(output.rglob('*')) if path.is_file() and path.name != 'evidence-sha256.json'}
save(output / 'evidence-sha256.json', source_manifest)
print(json.dumps({'status': verification['status'], 'raw_input_hash_checks': raw_verified,
                  'state_preserved': same_state, 'report': str(output / 'report.html')}, ensure_ascii=False))
