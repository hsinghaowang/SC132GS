"""ROS2 evidence evaluation using camera-stamped probe and common monotonic clock."""
import csv
import hashlib
import importlib.util
import json
import html
from pathlib import Path
import numpy as np

base=Path(__file__).resolve().parent
root=base/'ros-results'
spec=importlib.util.spec_from_file_location('euroc',base/'evaluate-euroc.py')
euroc=importlib.util.module_from_spec(spec);spec.loader.exec_module(euroc)
def read(path):
    with path.open() as file:return list(csv.DictReader(file))
def index_for(stamp,times,tolerance=5000):
    i=int(np.searchsorted(times,stamp));candidates=[j for j in (i-1,i) if 0<=j<len(times)]
    if not candidates:return None
    j=min(candidates,key=lambda j:abs(times[j]-stamp))
    return j if abs(times[j]-stamp)<=tolerance else None
results=[]
for output in sorted(root.glob('*')):
    if not output.is_dir() or not (output/'replay-summary.json').exists() or not (output/'receiver-summary.json').exists():continue
    replay=json.loads((output/'replay-summary.json').read_text())
    receiver=json.loads((output/'receiver-summary.json').read_text())
    events=read(output/'receiver-events.csv');published=read(output/'publish-events.csv');arrivals=read(output/'pose-arrivals.csv')
    pairs=[r for r in published if r['event']=='pair'];times=np.array([int(r['sensor_timestamp_ns']) for r in pairs],dtype=np.int64)
    first=receiver['first_initialized_camera_ns']
    eligible=np.flatnonzero(times>=first-5000) if first>=0 else np.array([],dtype=int)
    arrival_by={}; completion_by={};pair_received={};pair_begin={};camera_processing={};imu_ns=set();left_ns=set();right_ns=set()
    for r in arrivals:
        i=index_for(int(r['camera_timestamp_ns']),times)
        if i is not None:
            if i in arrival_by:raise RuntimeError('duplicate probe pose for camera frame')
            arrival_by[i]=int(r['arrival_monotonic_ns'])
    primary_stream='diagnostic camera-stamped probe'
    association_offsets=[];stock_trajectory=None
    if (output/'stock-pose-arrivals.csv').exists():
        stock=read(output/'stock-pose-arrivals.csv');arrival_by={}
        for r in stock:
            pose_ns=int(r['imu_timestamp_ns']);i=index_for(pose_ns,times,20_000_000)
            if i is None:raise RuntimeError('stock pose cannot be associated within 20 ms')
            if i in arrival_by:raise RuntimeError('stock pose association is not one-to-one')
            association_offsets.append(pose_ns-int(times[i]));arrival_by[i]=int(r['arrival_monotonic_ns'])
        primary_stream='stock /poseimu, calibrated IMU stamp associated one-to-one with nearest camera within 20 ms'
        stock_trajectory=np.array([[int(r['imu_timestamp_ns'])*1e-9]+[float(r[k]) for k in ('px','py','pz','qw','qx','qy','qz')] for r in stock])
        if len(stock_trajectory):np.savetxt(output/'stock-trajectory.csv',stock_trajectory,delimiter=',',header='timestamp_imu,px,py,pz,qw,qx,qy,qz')
    imu_published=[r for r in published if r['event']=='imu']
    imu_times=np.array([int(r['sensor_timestamp_ns']) for r in imu_published],dtype=np.int64)
    for r in events:
        ns=int(round(float(r['sensor_timestamp'])*1e9))
        if r['event']=='imu':
            i=index_for(ns,imu_times)
            if i is not None:imu_ns.add(i)
        elif r['event'] in ('left','right'):
            i=index_for(ns,times)
            if i is not None:(left_ns if r['event']=='left' else right_ns).add(i)
        elif r['event'] in ('pose','pair'):
            i=index_for(ns,times)
            if i is not None:(completion_by if r['event']=='pose' else pair_received)[i]=int(r['end_monotonic_ns'])
            if i is not None and r['event']=='pair':pair_begin[i]=int(r['begin_monotonic_ns'])
        elif r['event']=='camera_process':
            i=index_for(ns,times)
            if i is not None:camera_processing[i]=(int(r['begin_monotonic_ns']),int(r['end_monotonic_ns']))
    matched=sorted(arrival_by)
    lag=[(arrival_by[i]-int(pairs[i]['scheduled_monotonic_ns']))/1e6 for i in matched]
    publish_delay=[(int(pairs[i]['end_monotonic_ns'])-int(pairs[i]['scheduled_monotonic_ns']))/1e6 for i in matched]
    transport_to_pose=[(arrival_by[i]-int(pairs[i]['end_monotonic_ns']))/1e6 for i in matched]
    completion=[(completion_by[i]-int(pairs[i]['scheduled_monotonic_ns']))/1e6 for i in sorted(completion_by)]
    row={'run':output.name,'replay':replay,'receiver':receiver,'post_init_scheduled_frame_count':len(eligible),'observed_pose_coverage_after_init':len(arrival_by)/len(eligible) if len(eligible) else None,'scheduled_to_pose_arrival_ms':euroc.stats(lag),'scheduled_to_receiver_completion_ms':euroc.stats(completion),'scheduled_to_stereo_publish_complete_ms':euroc.stats(publish_delay),'stereo_publish_complete_to_pose_arrival_ms':euroc.stats(transport_to_pose),'matched_probe_frames':len(matched),'missing_probe_frame_indices':sorted(set(map(int,eligible))-set(arrival_by)) if len(eligible) else [],'input_missing':{'imu':replay['sent']['imu']-len(imu_ns),'left':replay['sent']['left']-len(left_ns),'right':replay['sent']['right']-len(right_ns),'paired_stereo':len(pairs)-len(pair_received)},'frame_match_tolerance_ns':5000,'clock_scope':'Same Linux host CLOCK_MONOTONIC; DDS + callback + estimator + headless visualization + probe receive; image load/serialization included in scheduled-to-arrival'}
    row['primary_pose_stream']=primary_stream
    if replay.get('prefetch_pairs',0):
        row['clock_scope']='Same Linux CLOCK_MONOTONIC; decode-ahead image schedule to stock-pose receive, including construction, DDS, pairing, estimator and probe. PNG decode runs before schedule when ready; any preparation delay remains in latency. Not physical exposure timing.'
    row['stock_pose_camera_association_offset_ms']=euroc.stats(np.abs(association_offsets)/1e6)
    row['intentional_active_stop']=replay['shutdown_mode']!='end_of_sequence'
    row['full_sequence_pose_coverage']=len(arrival_by)/len(pairs) if len(pairs) else None
    row['paired_callback_entry_to_worker_begin_ms']=euroc.stats([(camera_processing[i][0]-pair_begin[i])/1e6 for i in matched if i in camera_processing and i in pair_begin])
    row['worker_camera_update_and_publication_ms']=euroc.stats([(camera_processing[i][1]-camera_processing[i][0])/1e6 for i in matched if i in camera_processing])
    if replay['shutdown_mode']=='end_of_sequence' and receiver['poses']>=20:
        dataset=output.name.split('-paced')[0]
        gt=np.loadtxt(base/'feature-sweep/ground-truth'/f'{dataset}.csv',delimiter=',',comments='#');gt[:,0]*=1e-9
        trajectory=stock_trajectory if stock_trajectory is not None else np.loadtxt(output/'trajectory.csv',delimiter=',',comments='#',ndmin=2)
        row.update(euroc.accuracy(trajectory,gt))
        baseline=json.loads((base/'feature-sweep/results'/f'{dataset}-pts100-paced-1/evaluation.json').read_text())
        row['native_candidate_baseline']={'ate_rmse_m':baseline['ate_rmse_m'],'lag_p95_ms':baseline['initialized_lag_ms']['p95'],'scope':'different run; native estimator return, not ROS2 pose receive'}
    (output/'evaluation.json').write_text(json.dumps(row,indent=2));results.append(row)
(root/'evaluation.json').write_text(json.dumps(results,indent=2))
for row in results:
    print(row['run'],json.dumps({k:row.get(k) for k in ('input_missing','observed_pose_coverage_after_init','scheduled_to_pose_arrival_ms','ate_rmse_m','rpe_translation_rmse_m')}))
final=[r for r in results if '-paced-worker-' in r['run']]
parts=['<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>OpenVINS ROS2 回放驗證</title><style>body{font:16px/1.65 system-ui,sans-serif;max-width:1100px;margin:40px auto;padding:0 24px;color:#16263b}h1{font-size:28px}table{border-collapse:collapse;width:100%;margin:22px 0}td,th{padding:10px;border-bottom:1px solid #dce3eb;text-align:right}td:first-child,th:first-child{text-align:left}th{background:#edf4fb}.note{background:#f3f6fa;padding:16px;border-radius:8px}a{color:#1753bb}</style><h1>RUBIK Pi 3：OpenVINS ROS2 回放驗證</h1><p><strong>完整輸入／輸出與退出驗證完成；MH 延遲尾端仍待改善。</strong></p>',
    '<p>雙目 752×480／20 Hz、IMU 200 Hz；num_pts=100，分配為每眼目標 50 個。使用相同 EuRoC 設定與自然初始化，沒有真值初始化。</p>',
    '<table><tr><th>完整資料集</th><th>延遲 P95／P99／最大 ms</th><th>ATE cm</th><th>1秒 RPE cm／deg</th><th>初始化後位姿涵蓋率</th><th>漏收 IMU／雙目對</th></tr>']
for r in final:
    lag=r['scheduled_to_pose_arrival_ms'];miss=r['input_missing']
    parts.append(f"<tr><td>{html.escape(r['run'])}</td><td>{lag['p95']:.1f}／{lag['p99']:.1f}／{lag['max']:.1f}</td><td>{r['ate_rmse_m']*100:.2f}</td><td>{r['rpe_translation_rmse_m']*100:.2f}／{r['rpe_rotation_rmse_deg']:.3f}</td><td>{r['observed_pose_coverage_after_init']:.1%}</td><td>{miss['imu']}／{miss['paired_stereo']}</td></tr>")
parts+=['</table><p>兩個最終回放共 6,030 對影像／60,310 筆 IMU，初始化後 5,050 個位姿。全段位姿涵蓋率 MH 75.6%、V2 96.5%；自然初始化等待 MH 44.9 秒、V2 4.1 秒，初始化後 100% 不代表全段 100%。</p><p>延遲從來源影格的回放排程量到 stock /poseimu 的 DDS 接收，包含 PNG 讀取、影像訊息建立、DDS、雙目配對、等待 IMU、估測、狀態／路徑發布與位姿接收。所有時間點使用同一台 Linux 主機的 CLOCK_MONOTONIC。位姿 stamp 為校正後 IMU 時間，與來源影格逐筆做最近鄰一對一關聯，容許 20 ms，實際偏移見 evaluation.json。ATE 以位姿本身的 IMU stamp 對真值，不使用影格近似 stamp。</p>',
    '<div class="note">驗證的是自訂 C++17／PIMPL 接收器：ROS2 executor 只接收與複製資料；有界 4096 筆工作佇列；唯一 owned worker 存取估測器與視覺化發布，退出先 join，再關閉 ROS。IMU DDS 接收 KeepLast 100，影像 reliable KeepLast 10，ApproximateTime 配對 10。高頻 IMU odometry／TF 關閉，仍保留逐影格 stock 位姿與路徑發布。原版 detached subscriber main、高頻 odometry、實體相機／IMU與曝光到位姿延遲不在此次驗證範圍。</div>',
    '<h2>持續輸入時退出</h2>']
active=next((r for r in results if r['run']=='smoke-active-worker'),None)
if active:
    replay=active['replay'];recv=active['receiver']
    parts.append(f"<p>在 20 Hz 影像／200 Hz IMU 持續送出時送 SIGINT，接收器退出碼 {replay['receiver_exit_code']}，觀察到退出約 {replay['signal_to_exit_observed_ms']:.1f} ms；停止後發布器繼續送 {replay['sent_after_stop_signal']['left']} 對影像與 {replay['sent_after_stop_signal']['imu']} 筆 IMU。停止前收到 {recv['imu_received']} 筆 IMU，已輸出 {replay['observed_stock_poseimu']} 筆 stock 位姿。停止時主動放棄尚未處理量測 {recv.get('abandoned_measurements_at_stop',0)} 筆；此短測試的停止後輸入不列為正常運行漏收。</p>")
parts+=['<h2>延遲取捨</h2><p>MH 的影像讀取／發布 P95 為 32.7 ms，雙目回呼進入到估測工作開始 P95 為 94.4 ms、最高 365.7 ms，估測與狀態發布 P95 為 51.5 ms。工作佇列曾累積到 95 筆量測；未丟棄資料，所以會把短暫服務超時轉成排隊。V2 對應三項 P95 為 30.9／8.3／45.6 ms。各項是不同分布的百分位數，不能直接相加。</p><p>下一步先針對 MH 尖峰對照 tracking／更新內部時間及排隊時間，並比較較低影像訊息建立成本的發布器。未取得執行核心／排程追蹤，因此不把尖峰直接歸因於降頻或排程器。</p>',
    '<h2>先前版本與限制</h2><p>舊版將估測直接放在循序 ROS 回呼中，完整 V2／MH 分別漏收 408／1382 筆 IMU，延遲 P95 約 519／532 ms；原始紀錄保留為失敗診斷，不與新版合併。早期 Python bytes 影像訊息建立過慢，改用 array.array 才能維持 20 Hz。每份完整資料目前只跑一次；本結果是整合驗證，不代表產品誤差驗收或每幀 50 ms 截止時間保證。</p>',
    '<p>原生候選回放：MH P95 42.9–43.1 ms、ATE 12.00 cm；V2 P95 49.6–49.8 ms、ATE 5.47 cm。原生延遲量到估測返回，ROS2 量到 DDS 位姿收到，兩者量測終點不同。</p>',
    '<p><a href="evaluation.json">逐次完整評估</a> · <a href="conditions.json">環境／實作範圍</a> · <a href="evidence-sha256.json">證據雜湊</a></p></html>']
if (root/'exclusive-report.html').exists():
    parts.insert(1,'<div class="note">本頁保留先前未隔離背景負載的整合測試紀錄。最新三輪比較請看<a href="exclusive-report.html">暫停相機串流後的專用回放報告</a>。</div>')
(root/'report.html').write_text('\n'.join(parts),encoding='utf-8')
hashes={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file() and p.name!='evidence-sha256.json'}
(root/'evidence-sha256.json').write_text(json.dumps(hashes,indent=2))
