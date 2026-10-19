"""Read only downloaded logs; audit delivery without contacting the board."""
import csv
import json
from pathlib import Path
import numpy as np

root = Path(__file__).resolve().parent / 'ros-results'
comparison_path = root / 'prefetch-comparison-20261013/comparison.json'
comparison = json.loads(comparison_path.read_text())

def read(path):
    with path.open() as file:
        return list(csv.DictReader(file))

def distribution(values):
    if not values:
        return None
    return dict(zip(('p50', 'p95', 'p99', 'max'), map(float, np.r_[np.percentile(values, [50, 95, 99]), np.max(values)])))

for run in comparison['runs']:
    output = root / run['run']
    published = [row for row in read(output / 'publish-events.csv') if row['event'] == 'imu']
    stamps = np.array([int(row['sensor_timestamp_ns']) for row in published], dtype=np.int64)
    received = set()
    for event in read(output / 'receiver-events.csv'):
        if event['event'] != 'imu':
            continue
        stamp = int(round(float(event['sensor_timestamp']) * 1e9))
        index = int(np.searchsorted(stamps, stamp))
        nearest = min((i for i in (index - 1, index) if 0 <= i < len(stamps)), key=lambda i: abs(int(stamps[i]) - stamp))
        if abs(int(stamps[nearest]) - stamp) <= 5000:
            received.add(nearest)
    missing = sorted(set(range(len(stamps))) - received)
    receiver = json.loads((output / 'receiver-summary.json').read_text())
    assert len(received) == receiver['imu_received']
    assert len(missing) == run['input_missing']['imu']
    groups = []
    for index in missing:
        if groups and index == groups[-1][-1] + 1:
            groups[-1].append(index)
        else:
            groups.append([index])
    loss_set = set(missing)
    origin = int(json.loads((output / 'replay-summary.json').read_text())['origin_camera_timestamp_ns'])
    ledger = [dict(index=i, sensor_timestamp_ns=row['sensor_timestamp_ns'], received=i not in loss_set,
                   source_offset_s=(int(stamps[i]) - origin) / 1e9,
                   source_camera_phase_ms=((int(stamps[i]) - origin) % 50_000_000) / 1e6,
                   publication_lateness_ms=(int(row['begin_monotonic_ns']) - int(row['scheduled_monotonic_ns'])) / 1e6)
              for i, row in enumerate(published)]
    with (output / 'imu-receipt-audit.csv').open('w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=ledger[0].keys())
        writer.writeheader()
        writer.writerows(ledger)
    hist = dict(sorted((str(phase), sum(ledger[i]['source_camera_phase_ms'] == phase for i in missing))
                       for phase in set(row['source_camera_phase_ms'] for row in ledger)))
    audit = dict(sent=len(stamps), received=len(received), missing=len(missing),
                 missing_fraction=len(missing) / len(stamps), burst_count=len(groups),
                 longest_missing_burst=max(map(len, groups), default=0),
                 missing_source_camera_phase_counts=hist,
                 missing_publication_lateness_ms=distribution([ledger[i]['publication_lateness_ms'] for i in missing]),
                 received_publication_lateness_ms=distribution([ledger[i]['publication_lateness_ms'] for i in received]),
                 bursts=[dict(first_index=g[0], last_index=g[-1], count=len(g), source_offset_s=ledger[g[0]]['source_offset_s']) for g in groups],
                 ledger='imu-receipt-audit.csv',
                 conclusion='Receiver ingress missing counts agree with timestamp audit. No worker abandonment. Transport versus scheduling cause not established.')
    (output / 'imu-receipt-audit.json').write_text(json.dumps(audit, indent=2), encoding='utf-8')
    run['imu_receipt_audit'] = audit
    print(json.dumps(dict(run=run['run'], **{key: audit[key] for key in ('missing', 'burst_count', 'longest_missing_burst', 'missing_publication_lateness_ms', 'missing_source_camera_phase_counts')})))
comparison_path.write_text(json.dumps(comparison, indent=2), encoding='utf-8')
report_path = comparison_path.parent / 'report.html'
report = report_path.read_text(encoding='utf-8')
marker = '<h2>逐筆 IMU 離線定位</h2>'
if marker not in report:
    detail = marker + '<p>接收事件逐筆時間戳配對與接收器独立總數相符：MH 漏收 526／448 筆、V2 漏收 308／332 筆。全部都是單筆漏收，來源時間戳與影像相同或相差約 128 ns，沒有連續多筆中斷；漏掉的 IMU 在發布紀錄中仍存在，發布起始延遲 P95 約 0.52–0.57 ms。估測工作者停止時放棄量測為 0。這縮小到影像發布鄰近時段的接收／傳輸問題，尚不能直接判定 DDS 或排程器根因。</p><p>MH 未偵測到串流重疊的候選 ATE 為 22.26 cm，同期零漏收對照為 12.00 cm。較低延遲伴隨輸入不等價與精度差異，故不採用。</p>'
    report = report.replace('<h2>下一步</h2>', detail + '<h2>下一步</h2>')
    report_path.write_text(report, encoding='utf-8')
