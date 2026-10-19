"""Expected negative control, passing fixed profile, independent payload check."""
import hashlib
import json
from pathlib import Path
import subprocess
import time

base=Path('/home/ubuntu/ros2_humble_ws/slam_benchmark')
evidence=base/'ros-results/delivery-repair-20261013'
assert len(json.loads((evidence/'full-results.json').read_text()))==4
gate='source /opt/ros/humble/setup.bash\nsource /ws/slam_benchmark/openvins_ws/install/setup.bash\nexport ROS_DOMAIN_ID=73 ROS_LOCALHOST_ONLY=1 RMW_IMPLEMENTATION=rmw_fastrtps_cpp\n'
cases=[('512k','V2_02_medium-paced-delivery-gate-512k','fastdds-shm-512k.xml',4),
       ('4m','V2_02_medium-paced-delivery-gate-4m','fastdds-shm-4m.xml',0)]
results=[]
for label,name,profile,expected_exit in cases:
    script=gate+'export FASTRTPS_DEFAULT_PROFILES_FILE=/ws/slam_benchmark/'+profile+'\npython3 /ws/slam_benchmark/ros-replay-native-checked.py /ws/slam_benchmark/datasets/V2_02_medium/mav0 /ws/slam_benchmark/ros-results/'+name+' --frames 600 --prefetch-pairs 4\n'
    command_path=evidence/('gate-'+label+'.sh');command_path.write_text(script)
    with (evidence/('gate-'+label+'.log')).open('w') as log:
        result=subprocess.run(['docker','exec','ros2-humble','bash',str(command_path).replace('/home/ubuntu/ros2_humble_ws','/ws')],stdout=log,stderr=subprocess.STDOUT,timeout=80)
    summary=json.loads((base/'ros-results'/name/'replay-summary.json').read_text())
    item=dict(run=name,returncode=result.returncode,expected_returncode=expected_exit,input_integrity=summary['input_integrity'],DDS_profile=summary['DDS_profile'])
    results.append(item)
    (evidence/'gate-validation.json').write_text(json.dumps(results,indent=2))
    print(json.dumps(item),flush=True)
    assert result.returncode==expected_exit
    assert summary['input_integrity']['passed']==(expected_exit==0)
script=gate+'export FASTRTPS_DEFAULT_PROFILES_FILE=/ws/slam_benchmark/fastdds-shm-4m.xml\npython3 /ws/slam_benchmark/validate-prefetch-payload-4m.py\n'
command_path=evidence/'payload-4m.sh';command_path.write_text(script)
with (evidence/'payload-4m.log').open('w') as log:
    result=subprocess.run(['docker','exec','ros2-humble','bash',str(command_path).replace('/home/ubuntu/ros2_humble_ws','/ws')],stdout=log,stderr=subprocess.STDOUT,timeout=40)
assert result.returncode==0
payload=json.loads((base/'ros-results/delivery-shm4m-payload/validation.json').read_text())
print(json.dumps(payload),flush=True)
(evidence/'gate-source-provenance.json').write_text(json.dumps({name:hashlib.sha256((base/name).read_bytes()).hexdigest() for name in ('ros-replay-native-checked.py','validate-prefetch-payload-4m.py','validate-delivery-gate.py','run-frame-ready-replay.sh')},indent=2))
