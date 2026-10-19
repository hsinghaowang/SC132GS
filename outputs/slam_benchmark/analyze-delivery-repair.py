"""Verify transport repair without conflating process exit, delivery and accuracy."""
import csv
import hashlib
import html
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np

base=Path(__file__).resolve().parent
root=base/'ros-results'
evidence=root/'delivery-repair-20261013'
rows=json.loads((root/'evaluation.json').read_text())
full=json.loads((evidence/'full-results.json').read_text())
short=json.loads((evidence/'short-results.json').read_text())
load=[json.loads(line) for line in (evidence/'full-load.jsonl').read_text().splitlines()]
shm=[json.loads(line) for line in (evidence/'full-container-shm.jsonl').read_text().splitlines()]
assert len(full)==4 and len(short)==3
assert short[0]['input_missing']['imu']>0 and short[1]['input_missing']['imu']>0
assert not any(short[2]['input_missing'].values())

def read(path):
    with path.open() as file:return list(csv.DictReader(file))
def digest(output):
    value=hashlib.sha256()
    for event in read(output/'publish-events.csv'):
        value.update(f"{event['event']},{event['index']},{event['sensor_timestamp_ns']}\n".encode())
    return value.hexdigest()
def stats(values):
    return dict(zip(('p50','p95','p99','max'),map(float,np.r_[np.percentile(values,[50,95,99]),np.max(values)])))

small=ET.parse(base/'fastdds-shm-512k.xml')
large=ET.parse(base/'fastdds-shm-4m.xml')
ns={'dds':'http://www.eprosima.com/XMLSchemas/fastRTPS_Profiles'}
assert small.find('.//dds:segment_size',ns).text=='524288'
assert large.find('.//dds:segment_size',ns).text=='4194304'
small.find('.//dds:segment_size',ns).text='4194304'
assert ET.tostring(small.getroot())==ET.tostring(large.getroot()), 'single XML variable'
manifest=json.loads((evidence/'raw-sha256.json').read_text())
assert all(hashlib.sha256((root/path).read_bytes()).hexdigest()==value for path,value in manifest.items())
before=json.loads((evidence/'before.json').read_text())
after=json.loads((evidence/'full-after.json').read_text())
assert before['durable_sha256']==after['durable_sha256'] and before['runtime_sha256']==after['runtime_sha256']
assert 'ActiveState=inactive' in before['service'] and 'ActiveState=inactive' in after['service']
provenance=json.loads((evidence/'provenance.json').read_text())
assert provenance['ros2-runner/build/ros_replay_receiver']=='792c66116e2edddcb8877ec7fe488e29047dd38db28ea476306bc7722585b85f'
assert provenance['feature-sweep/configs/100/estimator_config.yaml']=='92b82dce6932b3289c0cd7152068219b87e21c585419908f7ee3558e2b66ec10'

selected=[];summary={}
for item in full:
    row=next(row for row in rows if row['run']==item['run'])
    output=root/row['run']
    assert not any(row['input_missing'].values()) and row['observed_pose_coverage_after_init']==1
    assert not item['returncode'] and not row['replay']['receiver_exit_code'] and not row['replay']['publisher_exit_code']
    assert not row['receiver']['abandoned_measurements_at_stop'] and not row['receiver']['error_code']
    assert row['receiver']['imu_received']==row['replay']['sent']['imu']
    samples=[sample for sample in load if item['start_monotonic_ns']<=sample['monotonic_ns']<=item['end_monotonic_ns']]
    unwanted=[dict(utc=sample['utc'],**process) for sample in samples for process in sample['processes']
              if process['comm'].startswith(('stereo-h265','sc132gs-fsync','cc1','ninja','make'))]
    assert samples and not unwanted, 'background overlap'
    observed_shm=[sample for sample in shm if item['start_monotonic_ns']<=sample['monotonic_ns']<=item['end_monotonic_ns']]
    assert any(sum(segment['size']>=4_194_304 for segment in sample['segments'])>=3 for sample in observed_shm), 'container SHM profile not observed'
    dataset=row['run'].split('-paced')[0]
    control=next(row for row in rows if row['run']==dataset+'-paced-pubcontrol-1')
    assert digest(output)==digest(root/control['run'])
    stages=read(output/'publisher-stages.csv')
    events=[event for event in read(output/'publish-events.csv') if event['event']=='pair']
    record=dict(run=row['run'],dataset=dataset,input_missing=row['input_missing'],
        scheduled_to_pose_ms=row['scheduled_to_pose_arrival_ms'],
        scheduled_to_stereo_publish_ms=row['scheduled_to_stereo_publish_complete_ms'],
        callback_entry_to_worker_ms=row['paired_callback_entry_to_worker_begin_ms'],
        worker_update_publication_ms=row['worker_camera_update_and_publication_ms'],
        ate_rmse_m=row['ate_rmse_m'],ate_delta_vs_control_m=row['ate_rmse_m']-control['ate_rmse_m'],
        rpe_translation_rmse_m=row['rpe_translation_rmse_m'],rpe_rotation_rmse_deg=row['rpe_rotation_rmse_deg'],
        post_init_pose_coverage=row['observed_pose_coverage_after_init'],full_sequence_pose_coverage=row['full_sequence_pose_coverage'],
        pairs=row['receiver']['pairs_received'],imu=row['receiver']['imu_received'],poses=row['replay']['observed_stock_poseimu'],
        maximum_prepared_queue=row['replay']['native_publisher_summary']['maximum_prepared_queue'],
        maximum_measurement_queue=row['receiver']['maximum_measurement_queue'],input_schedule_sha256=digest(output),
        background_monitor_samples=len(samples),forbidden_background_samples=unwanted,
        resources=row['replay']['resources'],
        prepared_before_due_fraction=sum(int(stage['load_end_ns'])<=int(events[int(stage['index'])]['scheduled_monotonic_ns']) for stage in stages)/len(stages),
        per_eye_decode_ms=stats([(int(stage['load_end_ns'])-int(stage['load_begin_ns']))/1e6 for stage in stages]))
    assert record['maximum_prepared_queue']<=4
    selected.append(record)
for dataset in ('MH_01_easy','V2_02_medium'):
    candidates=[row for row in selected if row['dataset']==dataset]
    control=next(row for row in rows if row['run']==dataset+'-paced-pubcontrol-1')
    summary[dataset]=dict(repeats=len(candidates),control_p95_ms=control['scheduled_to_pose_arrival_ms']['p95'],
        repaired_frame_ready_p95_range_ms=[min(row['scheduled_to_pose_ms']['p95'] for row in candidates),max(row['scheduled_to_pose_ms']['p95'] for row in candidates)],
        repaired_max_range_ms=[min(row['scheduled_to_pose_ms']['max'] for row in candidates),max(row['scheduled_to_pose_ms']['max'] for row in candidates)],
        control_ate_rmse_m=control['ate_rmse_m'],repaired_ate_rmse_m=[row['ate_rmse_m'] for row in candidates],
        receiver_cpu_percent_one_core=[row['resources']['receiver_cpu_percent'] for row in candidates],
        publisher_and_probe_cpu_percent_one_core=[row['resources']['publisher_probe_cpu_percent'] for row in candidates],
        max_absolute_ate_delta_m=max(abs(row['ate_delta_vs_control_m']) for row in candidates))
gate=json.loads((evidence/'gate-validation.json').read_text())
assert [item['returncode'] for item in gate]==[4,0]
assert not gate[0]['input_integrity']['passed'] and gate[1]['input_integrity']['passed']
payload=json.loads((root/'delivery-shm4m-payload/validation.json').read_text())
assert payload['exact_pixels_and_IMU_values'] and payload['left']==120 and payload['right']==120
accuracy_unchanged=all(value['max_absolute_ate_delta_m']<1e-6 for value in summary.values())
result=dict(status='passed_delivery_and_accuracy' if accuracy_unchanged else 'delivery_passed_accuracy_difference_requires_review',
    datasets=summary,runs=selected,short_transport_controls=short,gate_validation=gate,payload_validation=payload,
    raw_files_verified=len(manifest),camera_initially_inactive_and_preserved=True,receiver_and_yaml_unchanged=True,
    input_qos_unchanged='IMU publisher best effort KeepLast200, receiver best effort KeepLast100; images reliable KeepLast10',
    mitigation='Explicit process-local Fast DDS 4 MiB SHM segment instead of 512 KiB; no algorithm/binary changes',
    causal_limit='Single-variable segment-capacity intervention and reverse 512KiB control support transport-capacity cause. No internal overwrite trace captured.',
    measurement_limit='Frame-ready dataset replay: PNG decoded before source schedule; not equivalent to old PNG-on-path latency and not physical exposure-to-pose.',
    documentation='https://fast-dds.docs.eprosima.com/en/v2.6.11/fastdds/transport/shared_memory/shared_memory.html')
(evidence/'comparison.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(dict(status=result['status'],datasets=summary),indent=2))
parts=['<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>RUBIK Pi 3 IMU 傳輸修正</title>',
    '<style>body{font:16px/1.65 system-ui,sans-serif;max-width:1100px;margin:32px auto;padding:0 24px;color:#16263b}table{border-collapse:collapse;width:100%;margin:18px 0}td,th{padding:9px;border-bottom:1px solid #dce3eb;text-align:right}td:first-child,th:first-child{text-align:left}th{background:#edf4fb}.note{background:#f3f6fa;padding:16px;border-radius:8px}a{color:#1753bb}</style>',
    '<h1>RUBIK Pi 3：提前解碼的 IMU 傳輸修正</h1><p>2026-10-13。Fast DDS 2.6.12／ROS Humble。演算法、估測器 binary、YAML、發布器 binary 與 topic QoS 保持相同，針對 DDS 共用記憶體容量做單一變因對照。</p>',
    '<div class="note">4 MiB 容量的四次完整回放均零漏收、初始化後位姿涵蓋率 100%。延遲是<strong>提前解碼管線的影格排程到 stock 位姿接收</strong>；先前原版延遲包含排程後 PNG 解碼，量測範圍不同，且並非本輪同期延遲對照。不能將差額當成演算法加速，實體曝光到位姿仍未驗證。</div>',
    '<table><tr><th>資料集</th><th>原 PNG 路徑 P95 ms</th><th>已解碼回放 P95 ms</th><th>已解碼最大 ms</th><th>ATE cm</th></tr>']
for dataset,value in summary.items():
    p=value['repaired_frame_ready_p95_range_ms'];m=value['repaired_max_range_ms'];ate=value['repaired_ate_rmse_m']
    parts.append(f'<tr><td>{dataset}</td><td>{value["control_p95_ms"]:.1f}</td><td>{p[0]:.1f}–{p[1]:.1f}</td><td>{m[0]:.1f}–{m[1]:.1f}</td><td>{min(ate)*100:.3f}–{max(ate)*100:.3f}</td></tr>')
parts+=['</table><h2>完整回放驗證</h2><table><tr><th>回放</th><th>影像對／IMU</th><th>漏收</th><th>P95／P99／最大 ms</th><th>ATE cm</th><th>初始化後位姿</th></tr>']
for row in selected:
    lag=row['scheduled_to_pose_ms'];parts.append(f'<tr><td>{html.escape(row["run"])}</td><td>{row["pairs"]}／{row["imu"]}</td><td>0</td><td>{lag["p95"]:.1f}／{lag["p99"]:.1f}／{lag["max"]:.1f}</td><td>{row["ate_rmse_m"]*100:.3f}</td><td>{row["post_init_pose_coverage"]:.0%}</td></tr>')
parts+=['</table><h2>CPU 使用量</h2><table><tr><th>資料集</th><th>估測器 CPU %</th><th>發布器＋位姿接收 CPU %</th></tr>']
for dataset,value in summary.items():
    receiver=value['receiver_cpu_percent_one_core'];publisher=value['publisher_and_probe_cpu_percent_one_core']
    parts.append(f'<tr><td>{dataset}</td><td>{min(receiver):.1f}–{max(receiver):.1f}</td><td>{min(publisher):.1f}–{max(publisher):.1f}</td></tr>')
parts+=['</table><p>CPU 100% 代表一個邏輯核心，平均包含啟動、回放與收尾。發布器數據包含 PNG 提前解碼工作者，解碼成本仍存在。程序 peak RSS 不是各角色記憶體總和，完整資源與 /proc 抽樣見 comparison.json／full-load.jsonl。</p>',
    '<h2>容量對照與反向驗證</h2><p>600 對影像短測試：預設容量漏收 62 筆 IMU、明確 512 KiB 漏收 78 筆、4 MiB 零漏收。完整修正測試之後再改回 512 KiB，完整性檢查器回傳錯誤碼 4；4 MiB 回傳 0，證明正常退出不再被當作零漏收。新入口只對本次程序設定 DDS profile，不修改系統或其他工作的 DDS 環境。</p>',
    '<p>容器實際 IPC namespace 觀測到三個約 4 MiB 的 SHM 區段，設定確實生效。兩份 XML 除 segment_size 外相同。官方文件提醒太小的 segment 可能導致資料遺失；本次容量介入及反向對照支持傳輸容量原因，但沒有直接捕獲內部覆寫事件。<a href="https://fast-dds.docs.eprosima.com/en/v2.6.11/fastdds/transport/shared_memory/shared_memory.html">Fast DDS 說明</a>。</p>',
    '<p>獨立 DDS 接收驗證：120 對影像逐像素與全部 IMU 數值通過。四次完整回放的來源事件種類／索引／時間戳順序 SHA-256 與原對照相同。ATE 使用 stock 位姿的校正後 IMU stamp 對真值；全段位姿涵蓋率與初始化前缺口仍應看 comparison.json。</p>',
    '<h2>板上狀態</h2><p>使用者已暫停其他測試；開始與結束相機服務均 inactive，沒有本工作啟停串流。保存的相機設定／runtime state 雜湊相同，維持使用者原暫停狀態。相機、FSYNC 與編譯程序在四次完整回放監測中均未出現。</p>',
    '<p><a href="comparison.json">完整分段／對照</a> · <a href="provenance.json">受測執行檔與設定</a> · <a href="gate-validation.json">失敗／成功完整性檢查</a> · <a href="../prefetch-comparison-20261013/report.html">先前失敗候選</a> · <a href="../publisher-comparison-20261013/report.html">原發布器同期比較</a></p></html>']
(evidence/'report.html').write_text('\n'.join(parts),encoding='utf-8')
