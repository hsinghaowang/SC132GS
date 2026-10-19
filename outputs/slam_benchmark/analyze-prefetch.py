"""Decode-ahead comparison: frame-ready scheduled input, not exposure latency."""
import csv
import hashlib
import html
import json
from pathlib import Path
import numpy as np

base=Path(__file__).resolve().parent;root=base/'ros-results';evidence=root/'prefetch-comparison-20261013'
rows=json.loads((root/'evaluation.json').read_text())
load=[json.loads(line) for line in (evidence/'platform-load.jsonl').read_text().splitlines()]
def csvrows(path):
    with path.open() as f:return list(csv.DictReader(f))
def stats(values):
    return dict(zip(('p50','p95','p99','max'),map(float,np.r_[np.percentile(values,[50,95,99]),np.max(values)])))
def digest(output):
    h=hashlib.sha256()
    for r in csvrows(output/'publish-events.csv'):h.update(f"{r['event']},{r['index']},{r['sensor_timestamp_ns']}\n".encode())
    return h.hexdigest()
selected=[];summary={}
for dataset in ('MH_01_easy','V2_02_medium'):
    control=next(r for r in rows if r['run']==dataset+'-paced-pubcontrol-1')
    candidates=[next(r for r in rows if r['run']==dataset+f'-paced-prefetch-{i}') for i in (1,2)]
    expected=digest(root/control['run'])
    for row in candidates:
        functional=not any(row['input_missing'].values()) and row['observed_pose_coverage_after_init']==1
        assert row['replay']['receiver_exit_code']==0 and row['replay']['publisher_exit_code']==0
        assert row['receiver']['abandoned_measurements_at_stop']==0
        assert row['replay']['prefetch_pairs']==4 and row['replay']['native_publisher_summary']['maximum_prepared_queue']<=4
        assert digest(root/row['run'])==expected
        stages=csvrows(root/row['run']/'publisher-stages.csv')
        pairs=[r for r in csvrows(root/row['run']/'publish-events.csv') if r['event']=='pair']
        all_events=csvrows(root/row['run']/'publish-events.csv')
        start=int(row['replay']['start_monotonic_ns'])
        end=max(int(r['end_monotonic_ns']) for r in all_events)+2_000_000_000
        samples=[s for s in load if int(s['monotonic_ns'])>=start and int(s['monotonic_ns'])-int(s['interval_s']*1e9)<=end]
        background=[dict(utc=s['utc'],monotonic_ns=s['monotonic_ns'],**p) for s in samples for p in s['processes'] if p['comm'].startswith(('stereo-h265','sc132gs-fsync','cc1','ninja','make'))]
        times=np.array([int(r['sensor_timestamp_ns']) for r in pairs],dtype=np.int64)
        def near(ns):
            i=int(np.searchsorted(times,ns));return min((j for j in (i-1,i) if 0<=j<len(times)),key=lambda j:abs(int(times[j])-ns))
        poses=csvrows(root/row['run']/'stock-pose-arrivals.csv')
        lag=[(int(p['arrival_monotonic_ns'])-int(pairs[near(int(p['imu_timestamp_ns']))]['scheduled_monotonic_ns']))/1e6 for p in poses]
        record=dict(run=row['run'],lag_ms=row['scheduled_to_pose_arrival_ms'],
            functional_input_integrity_passed=functional,input_missing=row['input_missing'],
            camera_compiler_overlap_detected=bool(background),background_samples=background,
            background_monitor_samples=len(samples),eligible_for_valid_performance_comparison=functional and not background,
            image_publish_complete_ms=row['scheduled_to_stereo_publish_complete_ms'],
            callback_entry_to_worker_ms=row['paired_callback_entry_to_worker_begin_ms'],
            worker_update_publish_ms=row['worker_camera_update_and_publication_ms'],
            ate_rmse_m=row['ate_rmse_m'],rpe_translation_rmse_m=row['rpe_translation_rmse_m'],
            maximum_measurement_queue=row['receiver']['maximum_measurement_queue'],
            maximum_prepared_queue=row['replay']['native_publisher_summary']['maximum_prepared_queue'],
            fraction_over_50_ms=sum(x>50 for x in lag)/len(lag),frames_over_100_ms=sum(x>100 for x in lag),
            input_schedule_sha256=expected,pairs=row['receiver']['pairs_received'],imu=row['receiver']['imu_received'],
            poses=row['replay']['observed_stock_poseimu'],
            preparation_png_decode_ms=stats([(int(s['load_end_ns'])-int(s['load_begin_ns']))/1e6 for s in stages]),
            message_construction_ms=stats([(int(s['message_ready_ns'])-int(s['construction_begin_ns']))/1e6 for s in stages]),
            per_eye_publish_ms=stats([(int(s['publish_end_ns'])-int(s['message_ready_ns']))/1e6 for s in stages]),
            scheduled_to_publish_begin_ms=stats([(int(p['begin_monotonic_ns'])-int(p['scheduled_monotonic_ns']))/1e6 for p in pairs]),
            image_prepared_before_scheduled_fraction=sum(int(s['load_end_ns'])<=int(pairs[int(s['index'])]['scheduled_monotonic_ns']) for s in stages)/len(stages))
        selected.append(record)
    unconfounded=[r for r in selected if r['run'].startswith(dataset+'-') and not r['camera_compiler_overlap_detected']]
    summary[dataset]=dict(control_p95_ms=control['scheduled_to_pose_arrival_ms']['p95'],
        sampled_camera_off_runs=[r['run'] for r in unconfounded],
        diagnostic_imu_missing=[r['input_missing']['imu'] for r in unconfounded],
        valid_candidate_runs=[r['run'] for r in selected if r['run'].startswith(dataset+'-') and r['eligible_for_valid_performance_comparison']],
        decision='reject candidate as benchmark baseline: IMU input loss',
        candidate_p95_range_ms=[min(r['lag_ms']['p95'] for r in unconfounded),max(r['lag_ms']['p95'] for r in unconfounded)],
        candidate_max_range_ms=[min(r['lag_ms']['max'] for r in unconfounded),max(r['lag_ms']['max'] for r in unconfounded)],
        control_image_publish_p95_ms=control['scheduled_to_stereo_publish_complete_ms']['p95'],
        candidate_image_publish_p95_range_ms=[min(r['image_publish_complete_ms']['p95'] for r in unconfounded),max(r['image_publish_complete_ms']['p95'] for r in unconfounded)],
        control_ate_rmse_m=control['ate_rmse_m'],candidate_ate_rmse_m=[r['ate_rmse_m'] for r in unconfounded])
unwanted=[dict(utc=s['utc'],**p) for s in load for p in s['processes'] if p['comm'].startswith(('stereo-h265','sc132gs-fsync','cc1','ninja','make'))]
manifest=json.loads((evidence/'raw-sha256.json').read_text())
assert all(hashlib.sha256((root/path).read_bytes()).hexdigest()==value for path,value in manifest.items()), 'raw evidence integrity'
provenance=json.loads((evidence/'provenance.json').read_text())
checked={path:value for path,value in provenance.items() if (base/path).is_file()}
assert all(hashlib.sha256((base/path).read_bytes()).hexdigest()==value for path,value in checked.items()), 'tested source integrity'
payload=json.loads((root/'prefetch-payload-validation-2/validation.json').read_text());assert payload['exact_pixels_and_IMU_values']
stop=json.loads((root/'prefetch-active-stop/validation.json').read_text());assert stop['SIGINT_during_publishing'] and stop['interrupted_error_code']==3
hardware=json.loads((root/'publisher-comparison-20261013/camera-recovery/result.json').read_text())
result=dict(status='candidate_rejected_imu_input_loss',datasets=summary,runs=selected,payload_validation=payload,active_stop=stop,
    raw_evidence_files_verified=len(manifest),tested_local_source_hashes_verified=checked,
    board_after_batch_snapshot=json.loads((evidence/'platform-after.json').read_text()),
    user_confirms_other_job_running=True,
    forbidden_process_samples=unwanted,camera_recovery=hardware,
    scope='PNG decode moved before source schedule. Lower diagnostic latency is not a valid loss-free improvement. No exposure-to-pose/live sensor proof. No additional board work during other long-duration test.')
(evidence/'comparison.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(summary,indent=2))
parts=['<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>OpenVINS 提前解碼回放</title>',
    '<style>body{font:16px/1.65 system-ui,sans-serif;max-width:1120px;margin:32px auto;padding:0 24px;color:#16263b}table{border-collapse:collapse;width:100%;margin:18px 0}td,th{padding:9px;border-bottom:1px solid #dce3eb;text-align:right}td:first-child,th:first-child{text-align:left}th{background:#edf4fb}.note{background:#f3f6fa;padding:16px;border-radius:8px}a{color:#1753bb}</style>',
    '<h1>RUBIK Pi 3：提前解碼版本未通過輸入完整性檢查</h1><p>2026-10-13。估測器 binary／YAML 不變，位姿仍經 rclpy 接收 stock /poseimu。C++17 發布器增加 owned 解碼工作者、最多四對影像的準備佇列。原發布器零漏收版本保留為基準。</p>',
    '<div class="note"><strong>不能判定為效能改善：</strong>四次完整候選回放都有 IMU 漏收。最後 MH 第 2 次與另一工作啟動的相機串流重疊；前三次在相機／編譯程序未被抽樣偵測到的條件下已漏收，不能用最後一次的背景負載解釋全部問題。下表只列無該重疊的失敗診斷數據，沒有合格候選。</div>',
    '<div class="note"><strong>量測範圍已改變：</strong>原發布器把 PNG 讀取與解碼放在影格排程之後；本版本提前解碼，延遲由已準備影像的發布排程開始計算。解碼成本沒有消失，這是減少資料集回放工具對估測量測的干擾，不代表實體相機或曝光到位姿已達此延遲。</div>',
    '<table><tr><th>資料集</th><th>原發布器 P95 ms</th><th>候選診斷 P95 ms</th><th>候選診斷最大 ms</th><th>原影像發布 P95 ms</th><th>候選影像發布 P95 ms</th></tr>']
for dataset,v in summary.items():
    p=v['candidate_p95_range_ms'];m=v['candidate_max_range_ms'];image=v['candidate_image_publish_p95_range_ms']
    parts.append(f'<tr><td>{dataset}</td><td>{v["control_p95_ms"]:.1f}</td><td>{p[0]:.1f}–{p[1]:.1f}</td><td>{m[0]:.1f}–{m[1]:.1f}</td><td>{v["control_image_publish_p95_ms"]:.1f}</td><td>{image[0]:.1f}–{image[1]:.1f}</td></tr>')
parts+=['</table><table><tr><th>回放</th><th>相機／編譯重疊</th><th>P95／最大 ms</th><th>IMU 漏收／送出</th><th>ATE cm</th><th>有效比較</th></tr>']
for r in selected:
    lag=r['lag_ms'];parts.append(f'<tr><td>{html.escape(r["run"])}</td><td>{"偵測到" if r["camera_compiler_overlap_detected"] else "未偵測到"}</td><td>{lag["p95"]:.1f}／{lag["max"]:.1f}</td><td>{r["input_missing"]["imu"]}／{r["imu"]+r["input_missing"]["imu"]}</td><td>{r["ate_rmse_m"]*100:.3f}</td><td>未通過</td></tr>')
parts+=['</table><p>四次完整候選回放均正常退出、初始化後位姿涵蓋率 100%，但均漏收 IMU。事件種類／索引／時間戳順序 SHA-256 相同只表示發布器嘗試送出相同資料，不表示接收端全數收到。抽樣 24 對影像逐像素與 241 筆 IMU 數值短驗證通過；SIGINT 約 318 ms 退出、預期回報 Interrupted。兩者均不能取代完整回放的輸入完整性驗收。</p>',
    '<p>先前單純更換 C++ 發布器沒有明顯改善 MH：單眼 PNG 解碼 P95 約 16.6 ms，訊息建立 P95 不到 0.2 ms。原試驗的 source／原始資料與結果均保留，可由連結重建比較。</p>',
    '<h2>串流與其他工作</h2><p>本工作在 10:49 用原保存設定恢復相機，驗證因 capture timeout 失敗；同時有 SMMU fault，尚未證實因果。另一工作於 11:09:42 啟動串流，最後一次回放受影響。批次結束快照顯示 active、Linear 60、AE 關閉、gain 27；這是當時快照，並非新的長時間串流驗證。使用者確認另一工作正在長時間測試，後續僅在 Windows 本機分析，保留板上狀態。<a href="../publisher-comparison-20261013/camera-recovery/result.json">本工作恢復失敗紀錄</a>。</p>',
    '<h2>下一步</h2><p>離線對照逐筆 IMU 發布／接收、漏收連續區段與影像發布時段，責任位置尚未定案。待板子可用後，先驗收零輸入漏收與精度，再評估延遲；目前不切換到候選版本。</p>',
    '<p><a href="comparison.json">完整分段與驗證結果</a> · <a href="provenance.json">執行檔／設定雜湊</a> · <a href="../publisher-comparison-20261013/report.html">C++ 發布器同期對照</a> · <a href="../evaluation.json">所有逐次評估</a></p></html>']
(evidence/'report.html').write_text('\n'.join(parts),encoding='utf-8')
