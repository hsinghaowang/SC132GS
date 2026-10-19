"""DDS payload integration check against independent Python/OpenCV dataset reads."""
import csv
import json
from pathlib import Path
import subprocess
import time
import cv2
import rclpy
from sensor_msgs.msg import Image,Imu
from rclpy.qos import QoSProfile,ReliabilityPolicy
from rclpy.executors import SingleThreadedExecutor

base=Path('/ws/slam_benchmark')
data=base/'datasets/V2_02_medium/mav0'
out=base/'ros-results/delivery-shm4m-payload';out.mkdir(exist_ok=False)
def rows(p):
    with p.open() as f:return [r for r in csv.reader(f) if r and not r[0].startswith('#')]
left=rows(data/'cam0/data.csv')[:120];right=rows(data/'cam1/data.csv')[:120]
sources=[{int(r[0]):r[1] for r in eye} for eye in (left,right)]
imus={int(r[0]):list(map(float,r[1:])) for r in rows(data/'imu0/data.csv') if int(r[0])<=int(left[-1][0])+20_000_000}
seen=[set(),set(),set()];errors=[]
cv2.setNumThreads(1)
rclpy.init();node=rclpy.create_node('prefetch_payload_validation')
executor=SingleThreadedExecutor();executor.add_node(node)
def ns(msg):return msg.header.stamp.sec*10**9+msg.header.stamp.nanosec
def image(eye,msg):
    stamp=ns(msg)
    if stamp not in sources[eye] or stamp in seen[eye]:errors.append('unexpected or duplicate image stamp');return
    expected=cv2.imread(str(data/f'cam{eye}/data'/sources[eye][stamp]),cv2.IMREAD_GRAYSCALE)
    if (msg.height,msg.width,msg.step,msg.encoding,msg.header.frame_id)!=(480,752,752,'mono8',f'cam{eye}') or bytes(msg.data)!=expected.tobytes():errors.append('image metadata or pixels differ')
    seen[eye].add(stamp)
def imu(msg):
    stamp=ns(msg)
    values=[msg.angular_velocity.x,msg.angular_velocity.y,msg.angular_velocity.z,msg.linear_acceleration.x,msg.linear_acceleration.y,msg.linear_acceleration.z]
    if stamp not in imus or stamp in seen[2] or values!=imus.get(stamp) or msg.header.frame_id!='imu0':errors.append('IMU stamp or values differ')
    seen[2].add(stamp)
subs=[node.create_subscription(Image,f'/cam{eye}/image_raw',lambda msg,eye=eye:image(eye,msg),QoSProfile(depth=10,reliability=ReliabilityPolicy.RELIABLE)) for eye in (0,1)]
subs.append(node.create_subscription(Imu,'/imu0',imu,QoSProfile(depth=100,reliability=ReliabilityPolicy.BEST_EFFORT)))
process=None
try:
    with (out/'publisher.log').open('w') as log:
        process=subprocess.Popen([str(base/'native-publisher/build/native_replay_publisher'),str(data),str(out),'120','4'],stdout=log,stderr=subprocess.STDOUT)
        deadline=time.monotonic()+20
        while process.poll() is None and time.monotonic()<deadline:executor.spin_once(timeout_sec=.02)
        if process.poll() is None:raise RuntimeError('payload validation timed out')
        until=time.monotonic()+.5
        while time.monotonic()<until:executor.spin_once(timeout_sec=.02)
    assert process.returncode==0
    assert [len(x) for x in seen]==[120,120,len(imus)] and not errors,(list(map(len,seen)),len(imus),errors)
    result=dict(exact_pixels_and_IMU_values=True,left=len(seen[0]),right=len(seen[1]),imu=len(seen[2]))
    (out/'validation.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
finally:
    if process is not None and process.poll() is None:process.terminate();process.wait(timeout=5)
    executor.shutdown();executor.remove_node(node);node.destroy_node();rclpy.shutdown()
