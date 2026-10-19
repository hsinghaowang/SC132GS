"""Compare isolated replay repeats against earlier non-isolated evidence."""
import csv
import html
import json
from pathlib import Path
import numpy as np

root = Path(__file__).resolve().parent / 'ros-results'
rows = json.loads((root / 'evaluation.json').read_text())
exclusive = [r for r in rows if '-paced-exclusive-' in r['run']]
load = [json.loads(line) for line in (root / 'exclusive-platform-load.jsonl').read_text().splitlines()]
load_times = np.array([r['monotonic_ns'] for r in load], dtype=np.int64)
def csvrows(path):
    with path.open() as f:
        return list(csv.DictReader(f))
def stats(values):
    return dict(zip(('min', 'p50', 'p95', 'p99', 'max'), map(float, np.percentile(values, [0, 50, 95, 99, 100])))) if len(values) else None
details = []
for row in exclusive:
    path = root / row['run']
    pairs = [r for r in csvrows(path / 'publish-events.csv') if r['event'] == 'pair']
    camera = np.array([int(r['sensor_timestamp_ns']) for r in pairs], dtype=np.int64)
    events=csvrows(path / 'receiver-events.csv')
    worker = {int(round(float(r['sensor_timestamp'])*1e9)): r for r in events if r['event'] == 'camera_process'}
    callbacks = {int(round(float(r['sensor_timestamp'])*1e9)): r for r in events if r['event'] == 'pair'}
    callback_times = np.array(sorted(callbacks), dtype=np.int64)
    internal=np.loadtxt(path/'internal-timing.csv', delimiter=',', comments='#', ndmin=2)
    internal_times=np.array(np.rint(internal[:,0]*1e9), dtype=np.int64)
    worker_times = np.array(sorted(worker), dtype=np.int64)
    def nearest(ns, stamps):
        i = int(np.searchsorted(stamps, ns))
        return min((j for j in (i-1,i) if 0<=j<len(stamps)), key=lambda j:abs(int(stamps[j])-ns))
    frames = []
    for pose in csvrows(path / 'stock-pose-arrivals.csv'):
        idx = nearest(int(pose['imu_timestamp_ns']), camera)
        scheduled = int(pairs[idx]['scheduled_monotonic_ns'])
        arrival = int(pose['arrival_monotonic_ns'])
        wi = nearest(int(camera[idx]), worker_times)
        event = worker[int(worker_times[wi])]
        assert abs(int(worker_times[wi])-int(camera[idx]))<=5000
        ci=nearest(int(camera[idx]), callback_times)
        callback=callbacks[int(callback_times[ci])]
        assert abs(int(callback_times[ci])-int(camera[idx]))<=5000
        ii=nearest(int(pose['imu_timestamp_ns']), internal_times)
        stages=None
        if abs(int(internal_times[ii])-int(pose['imu_timestamp_ns']))<=20_000_000:
            stages=dict(zip(('tracking','propagation','msckf_update','slam_update','slam_delayed','retriangulation_marginalization','total'), map(float,internal[ii,1:]*1000)))
        sample = load[nearest(arrival, load_times)]
        frames.append(dict(frame_index=idx, sensor_camera_ns=int(camera[idx]),
            scheduled_monotonic_ns=scheduled, arrival_monotonic_ns=arrival,
            lag_ms=(arrival-scheduled)/1e6,
            publish_complete_ms=(int(pairs[idx]['end_monotonic_ns'])-scheduled)/1e6,
            callback_entry_to_worker_begin_ms=(int(event['begin_monotonic_ns'])-int(callback['begin_monotonic_ns']))/1e6,
            worker_ms=(int(event['end_monotonic_ns'])-int(event['begin_monotonic_ns']))/1e6,
            internal_stages_ms=stages,
            nearest_load_sample_distance_ms=abs(sample['monotonic_ns']-arrival)/1e6,
            nearest_load_sample=sample))
    lag=[f['lag_ms'] for f in frames]
    first = row['replay']['start_monotonic_ns']
    last = max(int(p['end_monotonic_ns']) for p in pairs)
    samples=[r for r in load if first<=r['monotonic_ns']<=last]
    thermal={}
    clocks={}
    unwanted=[]
    for sample in samples:
        for key, value in sample['thermal'].items():
            if value['type'].startswith(('cpu','cpuss')):
                thermal.setdefault(value['type'],[]).append(float(value['temperature_raw'])/1000)
        for key, value in sample['reported_cpu_clocks'].items():
            if 'scaling_cur_freq' in value:
                clocks.setdefault(key,[]).append(float(value['scaling_cur_freq'])/1000)
        for proc in sample['processes']:
            if proc['comm'].startswith(('stereo-h265','sc132gs-fsync','cc1','ninja','make')):
                unwanted.append(dict(utc=sample['utc'], **proc))
    detail=dict(run=row['run'], sample_count=len(samples), pose_count=len(frames),
        latency_ms=stats(lag), frames_over_50_ms=sum(x>50 for x in lag),
        fraction_over_50_ms=sum(x>50 for x in lag)/len(lag),
        frames_over_100_ms=sum(x>100 for x in lag),
        fraction_over_100_ms=sum(x>100 for x in lag)/len(lag),
        maximum_measurement_queue=row['receiver']['maximum_measurement_queue'],
        background_camera_or_compiler_samples=unwanted,
        cpu_thermal_c={k:stats(v) for k,v in thermal.items()},
        reported_scaling_frequency_mhz={k:stats(v) for k,v in clocks.items()},
        total_cpu_busy_percent=stats([r['cpu_busy_percent']['cpu'] for r in samples]),
        slowest_frames=sorted(frames,key=lambda f:f['lag_ms'],reverse=True)[:10])
    (path / 'exclusive-diagnostics.json').write_text(json.dumps(detail, indent=2))
    details.append(detail)
summary={}
for dataset in ('MH_01_easy','V2_02_medium'):
    runs=[r for r in exclusive if r['run'].startswith(dataset)]
    old=next(r for r in rows if r['run']==dataset+'-paced-worker-1')
    if not runs: continue
    summary[dataset]=dict(repeats=len(runs),
        earlier_nonisolated_ms=old['scheduled_to_pose_arrival_ms'],
        exclusive_p95_range_ms=[min(r['scheduled_to_pose_arrival_ms']['p95'] for r in runs),max(r['scheduled_to_pose_arrival_ms']['p95'] for r in runs)],
        exclusive_p99_range_ms=[min(r['scheduled_to_pose_arrival_ms']['p99'] for r in runs),max(r['scheduled_to_pose_arrival_ms']['p99'] for r in runs)],
        exclusive_max_range_ms=[min(r['scheduled_to_pose_arrival_ms']['max'] for r in runs),max(r['scheduled_to_pose_arrival_ms']['max'] for r in runs)],
        ate_range_m=[min(r['ate_rmse_m'] for r in runs),max(r['ate_rmse_m'] for r in runs)],
        all_input_loss_zero=all(not any(r['input_missing'].values()) for r in runs),
        all_post_init_coverage_complete=all(r['observed_pose_coverage_after_init']==1 for r in runs),
        all_exit_zero=all(r['replay']['receiver_exit_code']==0 for r in runs))
result=dict(summary=summary, per_run=details, scope=dict(
    latency='Dataset camera replay schedule to stock /poseimu DDS receive; same host CLOCK_MONOTONIC',
    earlier_comparison='Earlier one run per dataset had no matching process/thermal trace; not a randomized on/off causal experiment',
    telemetry='Read-only host /proc/sysfs sampled once per second; adds measurement overhead; scaling_cur_freq is reported policy frequency, not instruction-level clock or throttling proof',
    no_hardware_sensor_or_exposure_to_pose_measurement=True))
(root / 'exclusive-summary.json').write_text(json.dumps(result, indent=2))
print(json.dumps(summary, indent=2))

parts=['<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>OpenVINS 專用回放測試</title>',
    '<style>body{font:16px/1.65 system-ui,sans-serif;max-width:1180px;margin:32px auto;padding:0 24px;color:#16263b}table{border-collapse:collapse;width:100%;margin:18px 0}td,th{padding:9px;border-bottom:1px solid #dce3eb;text-align:right}td:first-child,th:first-child{text-align:left}th{background:#edf4fb}.note{background:#f3f6fa;padding:16px;border-radius:8px}a{color:#1753bb}</style>',
    '<h1>RUBIK Pi 3：暫停相機串流後的 ROS2 回放</h1>',
    '<p><strong>MH 大尖峰明顯縮小；兩份資料 P95 都約 79 ms，仍有 110–140 ms 尖峰。六次均無漏收，初始化後位姿完整，ATE 與先前相同。</strong></p>',
    '<p>相同 OpenVINS binary／YAML、雙目 752×480／20 Hz、IMU 200 Hz、num_pts=100（每眼目標 50）；兩份 EuRoC 資料各重複三次，第二輪反轉順序。相機串流與 FSYNC 已正常停止，測試期間以每秒一次的 /proc／sysfs 記錄負載。</p>',
    '<table><tr><th>資料集</th><th>先前 P95 ms</th><th>專用三輪 P95 ms</th><th>先前最大 ms</th><th>專用三輪最大 ms</th><th>ATE cm</th></tr>']
for dataset, value in summary.items():
    p=value['exclusive_p95_range_ms'];m=value['exclusive_max_range_ms'];a=value['ate_range_m'];old=value['earlier_nonisolated_ms']
    parts.append(f'<tr><td>{dataset}</td><td>{old["p95"]:.1f}</td><td>{p[0]:.1f}–{p[1]:.1f}</td><td>{old["max"]:.1f}</td><td>{m[0]:.1f}–{m[1]:.1f}</td><td>{a[0]*100:.3f}–{a[1]*100:.3f}</td></tr>')
parts+=['</table><h2>逐次結果</h2><table><tr><th>回放</th><th>P95／P99／最大 ms</th><th>超過 50／100 ms</th><th>配對等待 P95 ms</th><th>工作 P95 ms</th><th>最大佇列</th><th>漏收／涵蓋率</th></tr>']
for row, detail in zip(exclusive,details):
    lag=row['scheduled_to_pose_arrival_ms'];waiting=row['paired_callback_entry_to_worker_begin_ms'];work=row['worker_camera_update_and_publication_ms']
    miss=sum(row['input_missing'].values())
    parts.append(f'<tr><td><a href="{html.escape(row["run"])}/exclusive-diagnostics.json">{html.escape(row["run"])}</a></td><td>{lag["p95"]:.1f}／{lag["p99"]:.1f}／{lag["max"]:.1f}</td><td>{detail["fraction_over_50_ms"]:.1%}／{detail["fraction_over_100_ms"]:.1%}</td><td>{waiting["p95"]:.1f}</td><td>{work["p95"]:.1f}</td><td>{detail["maximum_measurement_queue"]}</td><td>{miss}／{row["observed_pose_coverage_after_init"]:.1%}</td></tr>')
parts+=['</table>',
    '<p>六次共接收 18,090 對影像與 180,930 筆 IMU，輸出 15,150 個初始化後位姿，退出碼全部為 0。CPU／程序記錄中未觀察到相機、FSYNC 或編譯程序。MH 最大量測佇列由先前 95 降到 21–28；回呼進入到工作開始 P95 由 94.4 ms 降到 6.9–7.2 ms。</p>',
    '<h2>剩餘延遲來自哪裡</h2><p>影像讀取／訊息建立／發布 P95：MH 33.2–33.4 ms、V2 31.7–32.0 ms；估測與狀態發布 P95：MH 43.9–44.7 ms、V2 46.3–46.5 ms。六次有 80.6–86.9% 的初始化後位姿在來源排程 50 ms 之後到達；可接收 20 Hz 完整序列不等於每幀延遲低於 50 ms。</p>',
    '<p>最慢的 V2 第三輪影格總延遲 140.2 ms，其中影像發布完成在 26.0 ms，回呼到工作開始 1.1 ms，估測／發布工作 110.6 ms；內部 SLAM delayed initialization 本身占 83.4 ms。這個影格的主要成本在估測工作，而非長時間排隊。其餘五輪最大延遲影格的延後地標初始化也占 30.7–66.6 ms，詳細逐幀分解保存在 exclusive-diagnostics.json。</p>',
    '<p>下一步優先降低回放發布器的影像建立成本，並檢查延後地標初始化的每幀工作量；任何估測參數變更都應重新比對完整輸入、ATE 與延遲。實體相機整合仍需要正確標定與時間基準。</p>',
    '<p>「涵蓋率」只計自然初始化後。全段初始等待仍存在：MH 約 44.9 秒，V2 約 4.1 秒。延遲從來源影格的排程時間量到 stock /poseimu 的 DDS 接收，包含 PNG 讀取、建立影像訊息、DDS、等待、估測與狀態／路徑發布。各段的百分位數不能相加。</p>',
    '<div class="note">舊結果每份資料只有一次，且沒有同步負載紀錄。因此此比較能描述暫停後的結果與重現性，無法把差異全部歸因於相機串流。監測程式本身也有負載。每秒一次的 CPU 頻率與溫度只適合觀察平台狀態，無法證明毫秒尖峰由降頻或排程造成。</div>',
    '<h2>證據範圍</h2><p>自訂 C++17／PIMPL ROS2 接收器、單一 owned worker、有界量測佇列；估測核心不變。高頻 IMU odometry／TF 關閉，逐影格 stock 位姿／路徑保留。未量測實體相機與 IMU、曝光到位姿延遲，或原版 detached subscriber main。</p>']
camera_path=root/'camera-pause-restore/result.json'
if camera_path.exists():
    camera=json.loads(camera_path.read_text())
    parts.append(f'<p>相機恢復：{html.escape(str(camera))}。恢復流程包含 RTSP 編碼速率與實際解碼驗證；設定檔雜湊保持不變，詳見<a href="camera-pause-restore/restore-camera.txt">恢復結果</a>與<a href="camera-pause-restore/provenance.json">設定／執行檔雜湊</a>。</p>')
parts+=['<p><a href="exclusive-summary.json">完整比較與平台／尖峰證據</a> · <a href="evaluation.json">逐次評估</a> · <a href="report.html">先前整合回放報告</a> · <a href="evidence-sha256.json">證據雜湊</a></p></html>']
(root/'exclusive-report.html').write_text('\n'.join(parts),encoding='utf-8')
