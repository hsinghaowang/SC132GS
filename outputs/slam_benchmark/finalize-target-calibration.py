import hashlib
import json
from pathlib import Path

base = Path(__file__).resolve().parent
ready = base / 'calibration-ready-20261014'
session = base / 'live-calibration-20261013/target-sweep-20261014'
geometry = ready / 'geometry-analysis'

def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

archive = base / 'calibration-target-20261014-evidence.tar'
assert digest(archive) == '372cd9f4d234a6f12ed4dd04f0cfde70d5ba3c8a2750710e49b70a76c41ce66d'
hashes = load(session / 'session-sha256.json')
verified = 0
missing_original_pgm = 0
for relative, expected in hashes.items():
    path = session / relative
    if path.exists():
        assert digest(path) == expected, relative
        verified += 1
    else:
        assert relative.startswith(('cam0/', 'cam1/')) and relative.endswith('.pgm'), relative
        missing_original_pgm += 1
assert missing_original_pgm == 898
audit = load(session / 'prepared/export-audit.json')
assert audit['png_pixel_roundtrip_passed'] and audit['SI_unit_conversion_all_rows_passed']
assert audit['images_written'] == 898
assert load(session / 'transaction.json')['saved_state_preserved']
report = load(geometry / 'report.json')
capture = load(session / 'camera-summary.json')
imu = load(session / 'imu-summary.json')
decode = load(ready / 'rtsp-windows/decode.json')
assert decode['passed'] and decode['decoded_frames'] >= 480
metrology = load(session / 'geometry-analysis/target-metrology.json')
assert metrology['square_size_m_reported'] == .020 and metrology['flat_mount_user_confirmed']
factory = report['factory_stereo']['errors']['held_out']
candidate = report['candidate']['errors']['held_out']
final_state = load(ready / 'final-state.json')
assert final_state['saved_camera_settings_unchanged']

result = dict(date='2026-10-14', timezone='Asia/Taipei', status='camera_only_stereo_candidate_obtained_pending_independent_coverage',
    session=str(session), board_session='/home/ubuntu/ros2_humble_ws/slam_benchmark/live-calibration-20261013/target-sweep-20261014',
    stereo_pairs=449, lossless_png_images=898, imu_samples=18834,
    camera_sequence_gaps=capture['driver_sequence_gaps'], camera_error_code=capture['error_code'],
    imu_restored=imu['restored'], sampled_pairs=60, complete_target_pairs=41,
    diverse_pose_representatives=13, fitting_poses=9, held_out_poses=4,
    factory_held_out_vertical=factory['vertical_error'], candidate_held_out_vertical=candidate['vertical_error'],
    target_metrology=metrology, factory_intrinsics_changed=False, EEPROM_writes=0,
    candidate_deployed=False, camera_imu_calibrated=False, live_VIO_performed=False,
    downloaded_session_files_verified=verified, board_original_PGM_files_hashed_and_retained=898,
    archive_sha256=digest(archive), archive_bytes=archive.stat().st_size,
    backup_scope='All 898 saved images backed up as pixel-identical PNG; original PGM and hashes retained on board',
    RTSP=dict(url='rtsp://192.168.137.226:8554/stereo', active_at_user_request=True,
              windows_decode=decode, initial_six_frame_snapshot_accepted_as_scene_proof=False),
    coverage=report['coverage'], final_state=final_state,
    next_step='Use RTSP to position a larger target at top/right/corners, then record an independent validation session. Camera-IMU common time and extrinsics remain separate work.')
save(ready / 'verification.json', result)

comparison = ''
for name, item in [('出廠外參', factory), ('新外參候選', candidate)]:
    values = item['vertical_error']
    comparison += f'<tr><td>{name}</td><td>{values["median_px"]:.3f}</td><td>{values["p95_px"]:.3f}</td><td>{values["max_px"]:.3f}</td><td>{item["cam0_pose_to_cam1_prediction_error"]["p95_px"]:.3f}</td></tr>'
report_html = f'''<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SC132GS：標定板採集與雙目外參候選</title><style>
*{{box-sizing:border-box}}body{{margin:0;color:#172e43;background:#eff3f8;font:16px/1.75 system-ui,sans-serif}}main{{max-width:1160px;margin:auto;padding:30px 22px 60px}}
h1{{font-size:29px;line-height:1.4;margin:8px 0 20px}}h2{{font-size:21px}}.muted{{color:#52677b}}.card{{background:white;border:1px solid #d8e2ec;border-radius:12px;padding:22px;margin:20px 0}}
.notice{{background:#fff2dc;border-left:4px solid #c68519;padding:12px 16px}}.metrics{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}}.metric{{padding:16px;background:#e7f1f8;border-radius:9px}}.number{{display:block;font-size:28px;font-weight:650;color:#164e72}}
table{{border-collapse:collapse;width:100%}}th,td{{padding:12px;border-bottom:1px solid #d7e1eb;text-align:left}}th{{background:#edf4f9}}a{{color:#0569a8}}img{{width:100%;height:auto;border-radius:6px}}code{{background:#e6edf4;padding:3px 6px}}details{{margin:15px 0}}.table{{overflow:auto}}@media(max-width:720px){{main{{padding:20px 12px}}h1{{font-size:24px}}.metrics{{grid-template-columns:1fr}}}}
</style></head><body><main>
<div class="muted">2026-10-14 · RUBIK Pi 3 / GS130WI / SC132GS</div>
<h1>標定板採集完成，已取得保留出廠內參的雙目外參候選</h1>
<div class="notice">目前為相機幾何候選，尚未套用到預覽或 OpenVINS。仍需擴大視野覆蓋並補一輪獨立驗證；相機–IMU 標定尚未完成。</div>
<section class="card"><h2>RTSP 預覽保持開啟</h2>
<p>VLC 使用 TCP 開啟：<code>rtsp://192.168.137.226:8554/stereo</code></p>
<p>Windows 實際解碼 {decode['decoded_frames']} 張，2176×1280、HEVC 10-bit、約 {decode['pts_fps']:.2f} FPS；已檢視棋盤場景。原本的持久設定不變，依使用者要求保持串流開啟。</p>
<details><summary>查看已解碼預覽截圖</summary><img src="rtsp-windows/decoded.png" alt="Windows 從目前 RTSP 解碼出的實體棋盤場景"></details></section>
<div class="metrics"><div class="metric"><span class="number">449 組</span>90 秒雙目影像，兩眼序號缺口皆為 0</div><div class="metric"><span class="number">898 張</span>PNG 與原始保存影像逐像素一致</div><div class="metric"><span class="number">18,834 筆</span>有效 IMU；相機共同時間仍待驗證</div></div>
<section class="card"><h2>保留出廠內參，只估計雙目外參</h2>
<p>抽查 60 組，其中 41 組兩眼均找到 9×6 完整角點。依位置、大小與傾角選出 13 個不同姿態代表：9 個用於求解，4 個完全保留作檢查。保持兩眼 fx/fy/cx/cy 與四個魚眼畸變係數不變。</p>
<div class="table"><table><thead><tr><th>4 個保留姿態／216 角點</th><th>上下偏差中位數 px</th><th>P95 px</th><th>最大 px</th><th>右眼姿態預測左眼 P95 px</th></tr></thead><tbody>{comparison}</tbody></table></div>
<p class="muted">上下偏差在 1088×1280 校正影像計算；報告 JSON 也保存統一 650 px 焦距後的比較。少量角點的最大偏差仍接近 4 px，未因平均改善而刪除。保留姿態來自同一次採集，不等同於獨立第二輪驗證。</p>
<p>兩眼單目重投影 RMS 分別為 0.337／0.425 px，這是保持出廠內參、分別擬合棋盤姿態的結果。候選外參相對出廠旋轉差約 0.287°，估計基線約 70.215 mm；尺度依使用者確認的 20 mm 格邊而定。</p>
<p><a href="geometry-analysis/stereo-candidate.yaml">下載相機專用候選 YAML</a> · <a href="geometry-analysis/report.json">完整數值與求解／保留姿態</a></p></section>
<section class="card"><h2>同一個保留姿態的校正預覽</h2>
<p>左半為 cam0／右眼，右半為 cam1／左眼；黃線標記相同影像列。</p>
<details><summary>使用出廠外參</summary><img src="geometry-analysis/factory-preview.png" alt="出廠外參對保留姿態的雙目校正預覽"></details>
<p>使用新外參候選：</p><img src="geometry-analysis/candidate-preview.png" alt="固定出廠內參並使用新雙目外參候選的保留姿態預覽"></section>
<section class="card"><h2>目前的範圍與下一輪</h2>
<p>角點聯集只覆蓋兩眼影像約 17.3%／19.0%，多集中於中下與偏左區域，棋盤約占畫面 3%～7%。傾角約 0.2°～41.5°。這批資料支持局部外參改善，尚不足以宣告全視野內參精度。</p>
<p>下一輪先利用 RTSP 把棋盤放得更大，涵蓋上方、右側與角落，再採集獨立驗證資料。棋盤保持平整、兩眼完整入鏡，每個位置停穩。相機與 IMU 的共同時間、外參方向、雜訊及 live VIO 仍需後續驗證。</p>
<p>使用者已確認橫、直格邊皆為 20 mm 且平整固定；本端未另以實體量具重測。採集時只暫用 gain index 0，結束後恢復原驅動控制，持久設定未變，未寫入 EEPROM。</p></section>
<section class="card"><h2>資料與驗證紀錄</h2>
<p><a href="verification.json">本輪驗證範圍</a> · <a href="../live-calibration-20261013/target-sweep-20261014/prepared/export-audit.json">PNG／IMU 匯出檢查</a> · <a href="../live-calibration-20261013/target-sweep-20261014/session-sha256.json">原始與衍生檔案雜湊</a></p>
<p>所有 898 張影像已在本機備份為逐像素相同的無損 PNG；原始 PGM 與完整來源快照保留在板上。板端根目錄：<code>/home/ubuntu/ros2_humble_ws/slam_benchmark/live-calibration-20261013/target-sweep-20261014</code>。</p>
<details><summary>方法與原始定義</summary><p>完整角點偵測後僅解決普通棋盤 180° 標號歧義。單目以出廠魚眼參數去畸變並擬合姿態；雙目使用 CALIB_FIX_INTRINSIC，未調整出廠 K/D。候選未寫回 EEPROM、未套用到 RTSP，未製造相機–IMU共同時間。</p>
<p><a href="https://docs.opencv.org/4.5.4/db/d58/group__calib3d__fisheye.html">OpenCV 魚眼投影與固定內參雙目求解</a></p></details></section>
</main></body></html>'''
(ready / 'report.html').write_text(report_html, encoding='utf-8')
status = load(base / 'openvins-status.json')
status['date'] = '2026-10-14'
status['physical_target_calibration'] = {
    'status': result['status'], 'report': 'calibration-ready-20261014/report.html',
    'stereo_pairs': 449, 'png_images': 898, 'imu_samples': 18834,
    'target_square_size_m_user_confirmed': .020, 'target_flat_mount_user_confirmed': True,
    'candidate': 'calibration-ready-20261014/geometry-analysis/stereo-candidate.yaml',
    'factory_intrinsics_unchanged': True, 'fitting_poses': 9, 'held_out_poses': 4,
    'held_out_factory_vertical': factory['vertical_error'], 'held_out_candidate_vertical': candidate['vertical_error'],
    'full_field_validation_complete': False, 'camera_IMU_calibration_complete': False,
    'candidate_deployed': False, 'RTSP_active_at_user_request': True,
}
status['next_step'] = result['next_step']
status['physical_calibration_preparation']['status'] = 'physical_target_capture_and_camera_only_candidate_obtained'
status['physical_calibration_preparation']['next_step'] = result['next_step']
status['physical_calibration_preparation']['physical_target_acquisition_complete'] = True
status['factory_calibration']['target_geometric_validation_performed'] = True
status['factory_calibration']['target_validation_scope'] = 'Limited image region; fixed-intrinsics mono pose fits and same-session held-out stereo poses; full-field acceptance pending'
save(base / 'openvins-status.json', status)
print(json.dumps(dict(status=result['status'], downloaded_session_files_verified=verified,
                     board_original_PGM_files=missing_original_pgm, report=str(ready / 'report.html')), ensure_ascii=False))
