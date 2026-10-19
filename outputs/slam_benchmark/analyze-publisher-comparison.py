"""Evaluate native publisher against contemporaneous controls, retaining pose probe."""
import csv
import hashlib
import html
import json
from pathlib import Path
import numpy as np

base=Path(__file__).resolve().parent
root=base/'ros-results'
evidence=root/'publisher-comparison-20261013'
rows=json.loads((root/'evaluation.json').read_text())
def read_csv(path):
    with path.open() as f:return list(csv.DictReader(f))
def stats(values):
    return dict(zip(('p50','p95','p99','max'),map(float,np.r_[np.percentile(values,[50,95,99]),np.max(values)])))
def digest_input(output):
    digest=hashlib.sha256()
    for r in read_csv(output/'publish-events.csv'):
        digest.update(f"{r['event']},{r['index']},{r['sensor_timestamp_ns']}\n".encode())
    return digest.hexdigest()
summary={};selected=[]
for dataset in ('MH_01_easy','V2_02_medium'):
    control=next(r for r in rows if r['run']==dataset+'-paced-pubcontrol-1')
    candidates=[next(r for r in rows if r['run']==dataset+f'-paced-nativepub-{i}') for i in (1,2)]
    inputs=digest_input(root/control['run'])
    for run in [control]+candidates:
        assert not any(run['input_missing'].values())
        assert run['observed_pose_coverage_after_init']==1
        assert run['replay']['receiver_exit_code']==0
        assert run['receiver']['abandoned_measurements_at_stop']==0
        assert digest_input(root/run['run'])==inputs, 'input stamp/order changed'
        item=dict(run=run['run'], input_schedule_sha256=inputs,
            lag_ms=run['scheduled_to_pose_arrival_ms'],publish_complete_ms=run['scheduled_to_stereo_publish_complete_ms'],
            callback_entry_to_worker_begin_ms=run['paired_callback_entry_to_worker_begin_ms'],
            worker_update_publish_ms=run['worker_camera_update_and_publication_ms'],
            ate_rmse_m=run['ate_rmse_m'],rpe_translation_rmse_m=run['rpe_translation_rmse_m'],
            maximum_measurement_queue=run['receiver']['maximum_measurement_queue'],
            publisher_and_probe_cpu_percent=run['replay']['resources']['publisher_probe_cpu_percent'],
            receiver_cpu_percent=run['replay']['resources']['receiver_cpu_percent'],
            pairs=run['receiver']['pairs_received'],imu=run['receiver']['imu_received'],
            poses=run['replay']['observed_stock_poseimu'])
        if 'nativepub' in run['run']:
            stages=read_csv(root/run['run']/'publisher-stages.csv')
            item['per_eye_stages_ms']={label:stats([(int(r[end])-int(r[start]))/1e6 for r in stages])
                for label,start,end in (('png_load','load_begin_ns','load_end_ns'),
                    ('message_construction','load_end_ns','message_ready_ns'),
                    ('publish','message_ready_ns','publish_end_ns'))}
        poses=read_csv(root/run['run']/'stock-pose-arrivals.csv')
        pairs=[r for r in read_csv(root/run['run']/'publish-events.csv') if r['event']=='pair']
        times=np.array([int(r['sensor_timestamp_ns']) for r in pairs],dtype=np.int64)
        def near(ns):
            i=int(np.searchsorted(times,ns))
            return min((j for j in (i-1,i) if 0<=j<len(times)),key=lambda j:abs(int(times[j])-ns))
        lag=[(int(p['arrival_monotonic_ns'])-int(pairs[near(int(p['imu_timestamp_ns']))]['scheduled_monotonic_ns']))/1e6 for p in poses]
        item['fraction_over_50_ms']=sum(x>50 for x in lag)/len(lag)
        item['frames_over_100_ms']=sum(x>100 for x in lag)
        selected.append(item)
    summary[dataset]=dict(control=control['run'],candidates=[r['run'] for r in candidates],
        control_p95_ms=control['scheduled_to_pose_arrival_ms']['p95'],
        candidate_p95_range_ms=[min(r['scheduled_to_pose_arrival_ms']['p95'] for r in candidates),max(r['scheduled_to_pose_arrival_ms']['p95'] for r in candidates)],
        candidate_max_range_ms=[min(r['scheduled_to_pose_arrival_ms']['max'] for r in candidates),max(r['scheduled_to_pose_arrival_ms']['max'] for r in candidates)],
        control_image_publish_p95_ms=control['scheduled_to_stereo_publish_complete_ms']['p95'],
        candidate_image_publish_p95_range_ms=[min(r['scheduled_to_stereo_publish_complete_ms']['p95'] for r in candidates),max(r['scheduled_to_stereo_publish_complete_ms']['p95'] for r in candidates)],
        control_ate_rmse_m=control['ate_rmse_m'],candidate_ate_rmse_m=[r['ate_rmse_m'] for r in candidates],input_schedule_sha256=inputs)
load=[json.loads(line) for line in (evidence/'platform-load.jsonl').read_text().splitlines()]
monitor=json.loads((evidence/'monitor.json').read_text())['pid']
monitor_cpu=[p['cpu_percent_one_core'] for r in load for p in r['processes'] if p['pid']==monitor]
unwanted=[dict(utc=r['utc'],**p) for r in load for p in r['processes'] if p['comm'].startswith(('stereo-h265','sc132gs-fsync','cc1','ninja','make'))]
assert not unwanted
before=json.loads((evidence/'platform-before.json').read_text());after=json.loads((evidence/'platform-after.json').read_text())
assert before['durable_sha256']==after['durable_sha256'] and before['runtime_state_sha256']==after['runtime_state_sha256']
result=dict(datasets=summary,runs=selected,monitor_cpu_percent_one_core=stats(monitor_cpu),
    camera_service_before=before['camera_service'],camera_service_after=after['camera_service'],
    camera_state_preserved=True,forbidden_background_process_samples=unwanted,
    scope=dict(pose_probe='Unchanged rclpy stock /poseimu endpoint; same QoS and callbacks',
        estimator='Identical receiver binary and YAML; no core changes',
        repeats='one contemporaneous Python control and two full C++ publisher runs per dataset',
        latency='source schedule to DDS stock pose receive; PNG decoding included',
        hardware=False,memory='Native publisher and Python probe are separate processes; reported role peak RSS is not their sum'))
(evidence/'comparison.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(summary,indent=2))
parts=['<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>OpenVINS C++ 發布器比較</title>',
    '<style>body{font:16px/1.65 system-ui,sans-serif;max-width:1120px;margin:32px auto;padding:0 24px;color:#16263b}table{border-collapse:collapse;width:100%;margin:18px 0}td,th{padding:9px;border-bottom:1px solid #dce3eb;text-align:right}td:first-child,th:first-child{text-align:left}th{background:#edf4fb}.note{background:#f3f6fa;padding:16px;border-radius:8px}a{color:#1753bb}</style>',
    '<h1>RUBIK Pi 3：C++ 發布器比較</h1><p>2026-10-13。原估測器與 YAML 保持不變，只將輸入端的 PNG 讀取／影像與 IMU 訊息發布改為 C++17。位姿接收與量測端仍是同一 rclpy probe；沒有影像預載。</p>',
    '<table><tr><th>資料集</th><th>原發布器 P95 ms</th><th>C++ P95 ms</th><th>C++ 最大 ms</th><th>原影像發布 P95 ms</th><th>C++ 影像發布 P95 ms</th></tr>']
for dataset,value in summary.items():
    p=value['candidate_p95_range_ms'];m=value['candidate_max_range_ms'];image=value['candidate_image_publish_p95_range_ms']
    parts.append(f'<tr><td>{dataset}</td><td>{value["control_p95_ms"]:.1f}</td><td>{p[0]:.1f}–{p[1]:.1f}</td><td>{m[0]:.1f}–{m[1]:.1f}</td><td>{value["control_image_publish_p95_ms"]:.1f}</td><td>{image[0]:.1f}–{image[1]:.1f}</td></tr>')
parts+=['</table><h2>逐次驗證</h2><table><tr><th>回放</th><th>P95／P99／最大 ms</th><th>超過 50 ms</th><th>ATE cm</th><th>最大佇列</th><th>發布器與 probe CPU</th></tr>']
for r in selected:
    lag=r['lag_ms']
    parts.append(f'<tr><td>{html.escape(r["run"])}</td><td>{lag["p95"]:.1f}／{lag["p99"]:.1f}／{lag["max"]:.1f}</td><td>{r["fraction_over_50_ms"]:.1%}</td><td>{r["ate_rmse_m"]*100:.3f}</td><td>{r["maximum_measurement_queue"]}</td><td>{r["publisher_and_probe_cpu_percent"]:.1f}%</td></tr>')
parts+=['</table><p>六次完整回放都沒有輸入漏收，初始化後位姿涵蓋率都是 100%，退出正常；每份資料在不同發布器下的事件種類／索引／時間戳順序 SHA-256 完全相同。CPU 100% 代表一個邏輯核心，數據含啟動、收尾與位姿接收。</p>',
    '<div class="note">延遲從回放排程到 stock /poseimu DDS 接收，包含 PNG 讀取與訊息發布，不是實體曝光到位姿延遲。這次每份資料只有一次同期原發布器對照與兩次候選版本；不能視為產品最差延遲保證。較低平均／P95 也不等於每幀都在 50 ms 內。</div>',
    '<h2>本批次條件與後續串流狀態</h2><p>這六次對照開始前相機服務已因 2026-10-12 20:18 capture timeout 失敗，六次量測期間未啟停相機，設定與 runtime state 雜湊前後相同。批次結束後本工作於 10:49 嘗試恢復相機，驗證失敗，並保存 timeout／同時 SMMU fault 紀錄；因果未定案。另一工作於 11:09:42 啟動串流，後續提前解碼第 4 次測試受影響。使用者確認另一工作正在長時間測試，本工作後續僅做 Windows 本機分析，保留板上狀態。</p>',
    '<p>此處測試的 C++ 發布器來源保存在 tested-sources；目前工作目錄的 C++ 發布器已有後續提前解碼實驗，不能用新版來源重建並宣稱是本六次量測的版本。<a href="../prefetch-comparison-20261013/report.html">提前解碼候選：因 IMU 漏收未通過</a>。</p>',
    '<p><a href="comparison.json">完整分段／驗證資料</a> · <a href="provenance.json">執行檔與設定雜湊</a> · <a href="../evaluation.json">逐次評估</a> · <a href="../exclusive-report.html">前一輪專用測試</a></p></html>']
(evidence/'report.html').write_text('\n'.join(parts),encoding='utf-8')
