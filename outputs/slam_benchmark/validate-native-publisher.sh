set -e
source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID=84 ROS_LOCALHOST_ONLY=1 RMW_IMPLEMENTATION=rmw_fastrtps_cpp
python3 - <<'PY'
import hashlib,json,pathlib,signal,subprocess,time
base=pathlib.Path('/ws/slam_benchmark');exe=base/'native-publisher/build/native_replay_publisher';data=base/'datasets/V2_02_medium/mav0'
smoke=base/'ros-results/V2_02_medium-paced-nativepub-smoke';summary=smoke/'native-publisher-summary.json'
before=hashlib.sha256(summary.read_bytes()).hexdigest()
r=subprocess.run([str(exe),str(data),str(smoke),'4'],capture_output=True,text=True,timeout=10)
assert r.returncode==1 and 'refuse to overwrite' in r.stderr
assert before==hashlib.sha256(summary.read_bytes()).hexdigest()
output=base/'ros-results/native-publisher-discovery-interrupt';output.mkdir(exist_ok=False)
with (output/'publisher.log').open('w') as log:
 p=subprocess.Popen([str(exe),str(data),str(output),'4'],stdout=log,stderr=subprocess.STDOUT)
 time.sleep(1);sent=time.monotonic_ns();p.send_signal(signal.SIGINT);p.wait(timeout=5);elapsed=(time.monotonic_ns()-sent)/1e6
native=json.loads((output/'native-publisher-summary.json').read_text());assert native['error_code']==3 and p.returncode==1
result=dict(refuses_evidence_overwrite=True,discovery_SIGINT_exit_code=p.returncode,discovery_SIGINT_error_code=native['error_code'],observed_stop_ms=elapsed)
(output/'validation.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
PY