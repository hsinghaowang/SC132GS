"""Publish local status only after evidence, accuracy and failure gates pass."""
import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path

base=Path(__file__).resolve().parent
root=base/'ros-results';evidence=root/'delivery-repair-20261013'
comparison=json.loads((evidence/'comparison.json').read_text())
assert comparison['status']=='passed_delivery_and_accuracy'
provenance=json.loads((evidence/'provenance.json').read_text())
for name,value in provenance.items():
    assert hashlib.sha256((evidence/'tested-sources'/name).read_bytes()).hexdigest()==value,name
gate_provenance=json.loads((evidence/'gate-source-provenance.json').read_text())
for name,value in gate_provenance.items():
    assert hashlib.sha256((evidence/'tested-sources'/name).read_bytes()).hexdigest()==value,name
    assert hashlib.sha256((base/name).read_bytes()).hexdigest()==value,name

class Links(HTMLParser):
    def __init__(self):super().__init__();self.links=[]
    def handle_starttag(self,tag,attrs):
        if tag=='a':self.links.extend(value for key,value in attrs if key=='href' and not value.startswith('https://'))
parser=Links();parser.feed((evidence/'report.html').read_text(encoding='utf-8'))
assert all((evidence/link).is_file() for link in parser.links)

status_path=base/'openvins-status.json';status=json.loads(status_path.read_text())
summary=dict(status=comparison['status'],report='ros-results/delivery-repair-20261013/report.html',
             summary='ros-results/delivery-repair-20261013/comparison.json',
             full_runs=4,input_loss=0,post_init_pose_coverage=1.0,
             receiver_binary_and_yaml_unchanged=True,topic_qos_unchanged=True,
             repair='Fast DDS process-local SHM segment_size=4194304',
             negative_control='512KiB lost IMU again after fixed full runs; checked runner exit4',
             entrypoint='run-frame-ready-replay.sh',
             input_gate='ros-replay-native-checked.py; exit4 on count loss, exit5 on incomplete receiver; evidence saved before failure',
             datasets=comparison['datasets'],physical_sensor_input=False,
             camera_initially_inactive_and_preserved=True,
             latency_scope='Prepared-image schedule to stock-pose DDS receive; PNG decode happens before schedule',
             historical_failure='Earlier prefetch-comparison-20261013 remains rejected, preserved without rewriting raw evidence')
status['date']='2026-10-13';status['delivery_repair']=summary
status['next_step']='Characterize remaining estimator timing peaks and integrate calibrated physical stereo/IMU with valid timestamps. Real-camera/IMU synchronization and exposure-to-pose latency are still unverified.'
status_path.write_text(json.dumps(status,indent=2,ensure_ascii=False),encoding='utf-8')
conditions_path=root/'conditions.json';conditions=json.loads(conditions_path.read_text())
conditions['delivery_repair']=summary
conditions['latest_verified_replay_report']='delivery-repair-20261013/report.html'
conditions_path.write_text(json.dumps(conditions,indent=2,ensure_ascii=False),encoding='utf-8')
verification=dict(status='passed',raw_files_verified=comparison['raw_files_verified'],
    frozen_experiment_sources_verified=len(provenance),input_gate_sources_verified=len(gate_provenance),
    report_relative_links_passed=True,capacity_single_variable=True,
    original_camera_off_state_preserved=True,
    source_sha256={name:hashlib.sha256((base/name).read_bytes()).hexdigest() for name in ('analyze-delivery-repair.py','finalize-delivery-repair.py','analyze-ros-replay.py')})
(evidence/'verification.json').write_text(json.dumps(verification,indent=2),encoding='utf-8')
hashes={str(path.relative_to(root)):hashlib.sha256(path.read_bytes()).hexdigest() for path in root.rglob('*') if path.is_file() and path.name!='evidence-sha256.json'}
(root/'evidence-sha256.json').write_text(json.dumps(hashes,indent=2),encoding='utf-8')
print(json.dumps(dict(status='passed',raw_files_verified=comparison['raw_files_verified'],local_inventory_files=len(hashes)),indent=2))
