"""Update local status and provenance after completed analysis and restoration."""
import hashlib
import json
from pathlib import Path

base=Path(__file__).resolve().parent
root=base/'ros-results'
def read(path): return json.loads(path.read_text(encoding='utf-8'))
def write(path, data): path.write_text(json.dumps(data,indent=2),encoding='utf-8')
evaluations=[r for r in read(root/'evaluation.json') if '-paced-exclusive-' in r['run']]
assert len(evaluations)==6
assert all(not any(r['input_missing'].values()) and r['observed_pose_coverage_after_init']==1
           and r['replay']['receiver_exit_code']==0 and r['receiver']['abandoned_measurements_at_stop']==0
           for r in evaluations)
camera=read(root/'camera-pause-restore/result.json')
assert camera['restored'] and camera['durable_unchanged'] and camera['benchmark_returncode']==0
diagnostics=read(root/'exclusive-summary.json')
assert all(not d['background_camera_or_compiler_samples'] for d in diagnostics['per_run'])
raw=read(root/'exclusive-raw-sha256.json')
assert all(hashlib.sha256((root/p).read_bytes()).hexdigest()==digest for p,digest in raw.items())
conditions=read(root/'conditions.json')
prior=root/'pre-exclusive-conditions.json'
if not prior.exists():write(prior,conditions)
conditions['exclusive_test']=dict(full_runs=6,repeats_per_dataset=3,
    camera_and_FSYNC_gracefully_stopped=True,restored_original_camera_configuration=True,
    binary_and_yaml_unchanged=True,order=['MH1','V2_1','V2_2','MH2','MH3','V2_3'],
    monitoring='read-only /proc and sysfs, once per second; monitor has CPU overhead',
    monitor_log='exclusive-platform-load.jsonl', report='exclusive-report.html',
    summary='exclusive-summary.json', raw_manifest='exclusive-raw-sha256.json',
    causal_limit='Earlier runs lack matching background process trace; differences cannot be attributed solely to camera stream')
conditions['limits'][0]='one earlier non-isolated full run plus three camera-paused full runs per dataset'
conditions['final_result']='zero input loss; complete post-init poses; camera-paused P95 about 79 ms, maxima 110-140 ms; physical sensor timing untested'
conditions['exclusive_source_sha256']={p:hashlib.sha256((base/p).read_bytes()).hexdigest() for p in
    ('run-exclusive-replay.sh','run-exclusive-host.py','sample-board-load.py',
     'run-exclusive-with-camera-restore.py','collect-exclusive-evidence.py','analyze-exclusive.py','analyze-ros-replay.py','finalize-exclusive.py')}
write(root/'conditions.json',conditions)
status=read(base/'openvins-status.json')
status['next_step']='Reduce replay image construction cost and investigate delayed landmark initialization workload; repeat latency and ATE checks after changes; physical stereo/IMU calibration and exposure-to-pose timing remain untested'
active=status['ros2_active_input_dataset_benchmark']
active.update(status='six_camera_paused_replays_passed_functional_checks_latency_tail_pending',
    report='ros-results/exclusive-report.html',final_runs=6,
    earlier_nonisolated_runs=2,input_pairs_received=sum(r['receiver']['pairs_received'] for r in evaluations),
    imu_samples_received=sum(r['receiver']['imu_received'] for r in evaluations),
    post_init_poses=sum(r['replay']['observed_stock_poseimu'] for r in evaluations),
    camera_restored=True, camera_configuration_unchanged=True,
    exclusive_comparison='ros-results/exclusive-summary.json')
write(base/'openvins-status.json',status)
write(root/'evidence-sha256.json',{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
    for p in root.rglob('*') if p.is_file() and p.name!='evidence-sha256.json'})
print(json.dumps(dict(runs=len(evaluations),input_pairs=active['input_pairs_received'],imu=active['imu_samples_received'],
    poses=active['post_init_poses'],raw_hashes_verified=len(raw),camera=camera),indent=2))
