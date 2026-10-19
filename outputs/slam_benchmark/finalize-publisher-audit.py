"""Finalize local evidence only; never connects to or loads the board."""
import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path
import shutil

base = Path(__file__).resolve().parent
root = base / 'ros-results'
prefetch = root / 'prefetch-comparison-20261013'
native = root / 'publisher-comparison-20261013'
audit = json.loads((prefetch / 'comparison.json').read_text())
verified = {}
for folder in (native, prefetch):
    manifest = json.loads((folder / 'raw-sha256.json').read_text())
    for path, digest in manifest.items():
        assert hashlib.sha256((root / path).read_bytes()).hexdigest() == digest, path
    verified[folder.name] = len(manifest)
initial = json.loads((native / 'provenance.json').read_text())
initial_sources = {}
for path in ('native-publisher/ReplayPublisher.hpp', 'native-publisher/ReplayPublisher.cpp', 'native-publisher/CMakeLists.txt', 'ros-replay-native.py'):
    saved = native / 'tested-sources' / path
    assert hashlib.sha256(saved.read_bytes()).hexdigest() == initial[path], str(saved)
    initial_sources[path] = initial[path]
provenance = json.loads((prefetch / 'provenance.json').read_text())
for path in ('native-publisher/ReplayPublisher.hpp', 'native-publisher/ReplayPublisher.cpp', 'native-publisher/CMakeLists.txt', 'ros-replay-native.py'):
    assert hashlib.sha256((base / path).read_bytes()).hexdigest() == provenance[path], path
    destination = prefetch / 'tested-sources' / path
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(base / path, destination)

class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.links = []
    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.links.extend(value for key, value in attrs if key == 'href')

for report in (native / 'report.html', prefetch / 'report.html'):
    parser = Links(); parser.feed(report.read_text(encoding='utf-8'))
    assert all((report.parent / link).is_file() for link in parser.links), str(report)
    assert '服務目前 failed' not in report.read_text(encoding='utf-8')
assert not any(run['eligible_for_valid_performance_comparison'] for run in audit['runs'])
assert sum(run['camera_compiler_overlap_detected'] for run in audit['runs']) == 1
assert next(run for run in audit['runs'] if run['camera_compiler_overlap_detected'])['run'] == 'MH_01_easy-paced-prefetch-2'
assert all('imu_receipt_audit' in run for run in audit['runs'])

status_path = base / 'openvins-status.json'
status = json.loads(status_path.read_text())
status['date'] = '2026-10-13'
status['next_step'] = 'Offline IMU delivery/scheduling diagnosis. Do not add board load during the other long-duration test. Revalidate zero input loss and accuracy before accepting decode-ahead latency.'
status['publisher_optimization'] = dict(
    date='2026-10-13', native_full_runs=6, native_input_loss=0,
    native_report='ros-results/publisher-comparison-20261013/report.html',
    prefetch_full_runs=4, prefetch_candidate_status='rejected_imu_input_loss',
    prefetch_camera_off_sampled_runs=3, prefetch_overlap_runs=['MH_01_easy-paced-prefetch-2'],
    prefetch_valid_performance_runs=0,
    prefetch_report='ros-results/prefetch-comparison-20261013/report.html',
    receiver_binary_and_yaml_unchanged=True,
    baseline='Original Python publisher plus owned-worker receiver: loss-free; about 78 ms P95 source-schedule-to-stock-pose receive',
    prefetch_measurement_scope='PNG decode moved before schedule; lower diagnostic latency with lost IMU is not an accepted improvement',
    other_long_duration_job_running_user_confirmed=True,
    board_work_deferred=True,
    camera_recovery_attempt='Failed capture timeout at 10:49; SMMU fault contemporaneous, causality unproven',
    camera_after_batch='Another job restarted stream at 11:09:42; active Linear60 AEoff gain27 in saved snapshot; no fresh live verification',
    historical_camera_restored_flag_scope='2026-10-12 original exclusive-test restoration only')
status_path.write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding='utf-8')
conditions_path = root / 'conditions.json'
conditions = json.loads(conditions_path.read_text())
conditions['latest_publisher_audit_date'] = '2026-10-13'
conditions['publisher_optimization'] = status['publisher_optimization']
conditions['final_result_scope'] = 'Existing final_result and exclusive_test describe historical loss-free worker/camera-paused runs. Decode-ahead is rejected, not part of that result.'
conditions_path.write_text(json.dumps(conditions, indent=2, ensure_ascii=False), encoding='utf-8')
verification = dict(raw_manifests_verified=verified, frozen_initial_native_sources_verified=initial_sources,
                    prefetch_tested_source_snapshot='tested-sources', valid_prefetch_performance_runs=0,
                    background_overlap_excluded='MH_01_easy-paced-prefetch-2',
                    independent_imu_count_and_timestamp_audit=True,
                    report_relative_links_passed=True,
                    board_contact_during_this_followup=False,
                    source_sha256={name: hashlib.sha256((base / name).read_bytes()).hexdigest() for name in (
                        'analyze-prefetch.py', 'audit-prefetch-imu.py', 'analyze-publisher-comparison.py', 'finalize-publisher-audit.py')})
(prefetch / 'verification.json').write_text(json.dumps(verification, indent=2), encoding='utf-8')
# This derived local inventory is separate from the immutable board raw manifests.
hashes = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
          for path in root.rglob('*') if path.is_file() and path.name != 'evidence-sha256.json'}
(root / 'evidence-sha256.json').write_text(json.dumps(hashes, indent=2), encoding='utf-8')
print(json.dumps(dict(raw_manifests_verified=verified, local_inventory_files=len(hashes),
                     reports_verified=True, candidate_status=audit['status']), indent=2))
