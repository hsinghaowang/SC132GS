"""Stop while publishing and while the owned image producer can be queue-blocked."""
import json
from pathlib import Path
import signal
import subprocess
import time
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.qos import QoSProfile,ReliabilityPolicy
from sensor_msgs.msg import Image,Imu

base=Path('/ws/slam_benchmark');out=base/'ros-results/prefetch-active-stop';out.mkdir(exist_ok=False)
rclpy.init();node=rclpy.create_node('prefetch_stop_validation');executor=SingleThreadedExecutor();executor.add_node(node)
counts={'left':0,'right':0,'imu':0}
def count(key,msg):counts[key]+=1
subs=[node.create_subscription(Image,topic,lambda msg,key=key:count(key,msg),QoSProfile(depth=10,reliability=ReliabilityPolicy.RELIABLE))
      for key,topic in (('left','/cam0/image_raw'),('right','/cam1/image_raw'))]
subs.append(node.create_subscription(Imu,'/imu0',lambda msg:count('imu',msg),QoSProfile(depth=100,reliability=ReliabilityPolicy.BEST_EFFORT)))
p=None
try:
    with (out/'publisher.log').open('w') as log:
        p=subprocess.Popen([str(base/'native-publisher/build/native_replay_publisher'),str(base/'datasets/V2_02_medium/mav0'),str(out),'1000','4'],stdout=log,stderr=subprocess.STDOUT)
        deadline=time.monotonic()+10
        while counts['left']<40 and p.poll() is None and time.monotonic()<deadline:executor.spin_once(timeout_sec=.02)
        assert counts['left']>=40 and p.poll() is None
        sent=time.monotonic_ns();p.send_signal(signal.SIGINT);p.wait(timeout=5);elapsed=(time.monotonic_ns()-sent)/1e6
    native=json.loads((out/'native-publisher-summary.json').read_text());assert native['error_code']==3 and p.returncode==1
    result=dict(SIGINT_during_publishing=True,owned_producer_joined_on_exit=True,exit_code=p.returncode,
                interrupted_error_code=native['error_code'],observed_stop_ms=elapsed,received_before_stop=counts)
    (out/'validation.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
finally:
    if p is not None and p.poll() is None:p.terminate();p.wait(timeout=5)
    executor.shutdown();executor.remove_node(node);node.destroy_node();rclpy.shutdown()
