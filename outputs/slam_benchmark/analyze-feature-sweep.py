"""Evaluate completed feature sweep runs, retaining incomplete/failing runs."""
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import numpy as np

base = Path(__file__).resolve().parent
root = base / 'feature-sweep'
spec = importlib.util.spec_from_file_location('euroc', base/'evaluate-euroc.py')
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)
rows = []
for output in sorted((root/'results').glob('*')):
    if not output.is_dir() or not (output/'resources.json').exists():
        continue
    dataset = output.name.split('-pts')[0]
    count = int(output.name.split('-pts')[1].split('-')[0])
    row = dict(run=output.name, dataset=dataset, num_pts=count, target_per_eye=count//2)
    row['resources'] = json.loads((output/'resources.json').read_text())
    if row['resources']['exit_code'] != 0 or not (output/'summary.json').exists():
        row['status'] = 'failed'; rows.append(row); continue
    summary = json.loads((output/'summary.json').read_text())
    row.update(summary)
    frames = np.genfromtxt(output/'frames.csv', delimiter=',', names=True)
    initialized = frames['initialized'] == 1
    service = frames['read_ms'] + frames['imu_ms'] + frames['estimator_ms']
    row['status'] = 'completed' if summary['frames'] == summary['input_frames'] else 'incomplete'
    row['all_frame_lag_ms'] = evaluation.stats(frames['completion_lag_ms'])
    row['initialized_lag_ms'] = evaluation.stats(frames['completion_lag_ms'][initialized])
    row['initialized_service_ms'] = evaluation.stats(service[initialized])
    row['service_over_50ms_fraction'] = float(np.mean(service[initialized]>50)) if initialized.any() else None
    row['pose_frame_coverage'] = summary['poses']/summary['frames']
    row['post_init_pose_coverage'] = summary['poses']/int(initialized.sum()) if initialized.any() else 0
    row['nonadvancing_initialized_frames'] = int(np.sum(initialized & (frames['state_advanced']==0)))
    row['initialization_delay_s'] = float(frames['camera_timestamp'][initialized][0]-frames['camera_timestamp'][0]) if initialized.any() else None
    if summary['poses'] >= 20:
        ground = np.loadtxt(root/'ground-truth'/f'{dataset}.csv', delimiter=',', comments='#')
        ground[:,0] *= 1e-9
        trajectory = np.loadtxt(output/'trajectory.csv', delimiter=',', comments='#', ndmin=2)
        try:
            row.update(evaluation.accuracy(trajectory,ground))
        except ValueError as error:
            row['accuracy_error'] = str(error)
    (output/'evaluation.json').write_text(json.dumps(row, indent=2))
    rows.append(row)
(root/'evaluation.json').write_text(json.dumps(rows, indent=2))
lines = ['# OpenVINS tracking feature sweep', '',
    'RUBIK Pi 3 / QCS6490; full EuRoC image + IMU replay, paced 20 Hz; native sequential runner. Physical cameras, IMU capture and ROS DDS are excluded.', '',
    '`num_pts` is divided by two cameras in the pinned implementation. Baseline 200 means target 100 per eye. Initializer target remains 50 total; only tracker num_pts changes. Actual tracked feature counts depend on the scene.', '',
    '| Dataset | num_pts (per eye target) | Repeat | Lag P95/P99/max ms* | Service P95 ms* | >50 ms service* | ATE m | 1s RPE m / deg | Pose coverage after init |',
    '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
for row in rows:
    if row['status']!='completed' or not row.get('initialized_lag_ms') or 'ate_rmse_m' not in row:
        lines.append(f"| {row['run']} | {row['num_pts']} | — | {row['status']} | — | — | — | — | — |")
        continue
    lag=row['initialized_lag_ms']; service=row['initialized_service_ms']
    lines.append(f"| {row['dataset']} | {row['num_pts']} ({row['target_per_eye']}) | {row['run'].rsplit('-',1)[1]} | {lag['p95']:.1f} / {lag['p99']:.1f} / {lag['max']:.1f} | {service['p95']:.1f} | {row['service_over_50ms_fraction']:.1%} | {row['ate_rmse_m']:.4f} | {row['rpe_translation_rmse_m']:.4f} / {row['rpe_rotation_rmse_deg']:.3f} | {row['post_init_pose_coverage']:.1%} |")
lines += ['', '* Post-initialization frames. Lag is replay schedule to completion, including PNG read/decode and IMU feed; service is read + IMU + estimator. It is not exposure-to-pose hardware latency.', '',
    'ATE uses full-trajectory SE3 alignment, scale fixed to 1. RPE is evaluated at 1 second. No ground-truth initialization. Settings 150 and 200 have one screening run per dataset; num_pts=100 additionally has confirmation runs as listed. Fresh baseline runs allow comparison without reusing the earlier baseline measured at a different time.']
(root/'report.md').write_text('\n'.join(lines)+'\n')
confirmation = {}
for dataset in ('MH_01_easy','V2_02_medium'):
    candidate = [r for r in rows if r['dataset']==dataset and r['num_pts']==100]
    completed = [r for r in candidate if r['status']=='completed' and 'ate_rmse_m' in r]
    confirmation[dataset] = {
        'completed_repeats':len(completed),
        'expected_repeats':3,
        'runs':[r['run'] for r in completed],
        'all_input_frames_processed':all(r['frames']==r['input_frames'] for r in completed) if completed else False,
        'all_post_init_poses_advance':all(r['nonadvancing_initialized_frames']==0 and r['post_init_pose_coverage']==1 for r in completed) if completed else False,
    }
    if completed:
        for key,values in {
            'lag_p95_ms':[r['initialized_lag_ms']['p95'] for r in completed],
            'lag_p99_ms':[r['initialized_lag_ms']['p99'] for r in completed],
            'lag_max_ms':[r['initialized_lag_ms']['max'] for r in completed],
            'service_p95_ms':[r['initialized_service_ms']['p95'] for r in completed],
            'service_over_50ms_fraction':[r['service_over_50ms_fraction'] for r in completed],
            'ate_rmse_m':[r['ate_rmse_m'] for r in completed],
        }.items():
            confirmation[dataset][key] = {'min':min(values),'max':max(values),'per_run':values}
(root/'confirmation.json').write_text(json.dumps(confirmation,indent=2))
screen = [r for r in rows if r['run'].endswith('-1')]
if len(screen)==6 and all(r['status']=='completed' and 'ate_rmse_m' in r for r in screen):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1,2,figsize=(10,4.2), constrained_layout=True)
    colors = {'MH_01_easy':'#2563eb','V2_02_medium':'#d97706'}
    for dataset,color in colors.items():
        series = sorted((r for r in screen if r['dataset']==dataset),key=lambda r:r['num_pts'])
        x = [r['target_per_eye'] for r in series]
        axes[0].plot(x,[r['initialized_lag_ms']['p95'] for r in series],'o-',color=color,label=dataset)
        axes[1].plot(x,[r['ate_rmse_m']*100 for r in series],'o-',color=color,label=dataset)
    for ax in axes:
        ax.set_xlabel('Tracking target per camera'); ax.set_xticks([50,75,100]); ax.grid(alpha=.2); ax.legend()
    axes[0].axhline(50,color='#64748b',ls='--',lw=1,label='50 ms input interval')
    axes[0].set_ylabel('Post-initialization completion lag P95 (ms)')
    axes[1].set_ylabel('Position ATE RMSE (cm, SE3 alignment)')
    fig.suptitle('RUBIK Pi 3 / OpenVINS — 20 Hz EuRoC replay, one run per setting')
    fig.savefig(root/'comparison.png',dpi=160)
    fig.savefig(root/'comparison.svg')
    plt.close(fig)
hashes = {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file() and p.name!='evidence-sha256.json'}
(root/'evidence-sha256.json').write_text(json.dumps(hashes,indent=2))
print('\n'.join(lines))
