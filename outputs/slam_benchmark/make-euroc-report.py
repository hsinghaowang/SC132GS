import json
import sys
from pathlib import Path

root=Path(sys.argv[1])
runs=json.loads((root/'evaluation.json').read_text())['runs']
assert len(runs)==12
assert all(r['resources']['exit_code']==0 and r['frames']==r['input_frames'] and r['post_initialization_pose_frame_coverage']==1 for r in runs)
mh=[r for r in runs if r['run']=='MH_01_easy-paced-3'][0]
v2=[r for r in runs if r['dataset']=='V2_02_medium' and r['paced']]
def span(values, digits=1):
    return f'{min(values):.{digits}f}–{max(values):.{digits}f}'
lines=[
    '# OpenVINS：RUBIK Pi 3 / QCS6490 EuRoC 實測',
    '',
    '已完成兩個資料集、每個資料集 3 次不限速及 3 次 20 Hz 播放，共 12 次完整回放。全部影像已處理，初始化後每個影像時間都有位姿更新。CPU 可持續處理這兩組 20 Hz 輸入，但仍有延遲尖峰；目前不能宣稱低延遲即時系統。',
    '',
    '以下延遲取 MH 最後一輪及 V2 三輪；這些輪次沒有並行的資料下載或解壓。延遲從排定的影像時間算到位姿完成，包含無損 PNG 載入／解碼與 IMU 插值所需的下一筆資料。它不是實體曝光到位姿的延遲，也未包含 ROS DDS 傳輸。',
    '',
    '| 資料集 | 自行初始化 | 位置 ATE RMSE | 估測 p95 | 播放到位姿 p95 | 最高播放延遲 |',
    '|---|---:|---:|---:|---:|---:|',
    f"| MH_01_easy（最後一輪） | {mh['initialization_delay_dataset_s']:.1f} s | {mh['ate_rmse_m']*100:.1f} cm | {mh['initialized_frame_processing_ms']['p95']:.1f} ms | {mh['playback_completion_lag_ms']['p95']:.1f} ms | {mh['playback_completion_lag_ms']['max']:.1f} ms |",
    f"| V2_02_medium（三輪） | {v2[0]['initialization_delay_dataset_s']:.1f} s | {span([r['ate_rmse_m']*100 for r in v2])} cm | {span([r['initialized_frame_processing_ms']['p95'] for r in v2])} ms | {span([r['playback_completion_lag_ms']['p95'] for r in v2])} ms | {span([r['playback_completion_lag_ms']['max'] for r in v2])} ms |",
    '',
    '初始化後、包含影像載入的不限速處理能力：',
    '',
    '| 資料集 | 組／秒（三輪） | 條件 |',
    '|---|---:|---|',
]
for name in ('MH_01_easy','V2_02_medium'):
    chosen=[r for r in runs if r['dataset']==name and not r['paced']]
    condition='探索性結果；V2 資料下載並行' if name=='MH_01_easy' else '沒有並行資料準備'
    lines.append(f"| {name} | {span([r['initialized_processing_pair_rate_hz'] for r in chosen])} | {condition} |")
lines += [
    '',
    f"估測程式的最高 RSS 為 {max(r['resources']['peak_rss_mib'] for r in runs):.1f} MiB。CPU 使用率以 100% 代表一個核心，各次回放平均為 {span([r['resources']['average_cpu_percent'] for r in runs])}%。這些數字包含本次原生回放的影像解碼，未包含 ROS 發布、GUI 或實體擷取程式。",
    '',
    'MH 前兩輪 20 Hz 播放與資料準備重疊，延遲最高分別約 440 ms 與 4.27 s；保留為背景負載觀察，不與最後一輪合併成受控重複測試。動態時脈與作業系統排程未調整，尚未證明降頻原因。',
    '',
    '## 方法與證明範圍',
    '',
    '- 板上 ARM64 Release 執行，OpenVINS 固定版本 `69488123ed9362dd44b6f28e7f4680abbff1442b`，估測核心未改。既有 ROS 結束生命週期修補有保存。',
    '- 官方 EuRoC 設定：雙目 752×480／20 Hz，IMU 200 Hz，num_pts=200（實作分配為每眼目標 100 個特徵）、4 個 OpenCV 執行緒、11 個 clones、50 個 SLAM features；啟用原設定的線上相機與時間偏移校正。',
    '- 原生循序回放；關閉 subscriber／publisher 背景執行緒。沒有 viewer、實體感測器、ROS DDS 輸入及 GPU／NPU 加速路徑。',
    '- 全序列從頭開始，不跳過初始化片段，不使用真值初始化。MH 全序列位姿涵蓋率約 75.6%，V2 約 96.5%；差異來自初始化等待，初始化後都是 100%。',
    '- ATE 對有效估計與真值重疊區間做完整軌跡 SE(3) 剛體對齊，不修正尺度。RPE 間隔 1 秒，真值位置與姿態插值規則、匹配數保存在 JSON。',
    '- [EuRoC 官方資料說明](https://projects.asl.ethz.ch/datasets/euroc-mav/)。本次下載來自鏡像，完整檔案 SHA-256 已與鏡像 LFS metadata 核對。尚未獨立證明與 ETH 原始典藏逐 byte 相同。',
    '- 目前結果可支持 CPU 資料集 VIO 可行性；SC132GS／ICM-42688 的實體同步、校正、ROS 傳輸與曝光到位姿延遲仍待端到端驗證。',
    '',
    '## 全部輪次',
    '',
    '| 輪次 | 影像／位姿數 | ATE cm | 估測 p95 ms | 播放延遲 p95 ms | 1 s RPE 平移 cm／旋轉 deg |',
    '|---|---:|---:|---:|---:|---:|',
]
for r in runs:
    lag=f"{r['playback_completion_lag_ms']['p95']:.1f}" if r['paced'] else '—'
    lines.append(f"| {r['run']} | {r['frames']}／{r['poses']} | {r['ate_rmse_m']*100:.2f} | {r['initialized_frame_processing_ms']['p95']:.1f} | {lag} | {r['rpe_translation_rmse_m']*100:.2f}／{r['rpe_rotation_rmse_deg']:.3f} |")
lines += ['', '原始紀錄包含每幀讀取、IMU 與估測時間、位姿、內部階段時間、RSS／CPU、熱感測器原值及 CPU 時脈。來源、設定雜湊與背景條件另有保存。', '', '重跑入口位於板上 `/home/ubuntu/ros2_humble_ws/slam_benchmark/`：在 `ros2-humble` 容器內執行 `/ws/slam_benchmark/run-euroc.sh` 與 `/ws/slam_benchmark/run-vicon2.sh`；腳本已固定 workspace、資料集與三次重複。重新執行會覆寫相同輪次的結果，需先保存舊紀錄。', '']
(root/'report.md').write_text('\n'.join(lines),encoding='utf-8')
print('PASS: 12 complete runs; all initialized frames advance pose; report saved')

