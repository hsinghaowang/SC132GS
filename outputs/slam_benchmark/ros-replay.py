"""ROS2 EuRoC publisher/probe and receiver lifecycle coordinator.

Sensor stamps remain EuRoC time. Cross-process timing uses Linux CLOCK_MONOTONIC.
No ROS simulated clock, viewer, or physical sensor input is involved.
"""
import argparse
import array
import csv
import heapq
import json
import os
import signal
import resource
import subprocess
import threading
import time
from pathlib import Path

import cv2
import rclpy
from rclpy.executors import ExternalShutdownException
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
from sensor_msgs.msg import Image, Imu
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy

def read_rows(path):
    with path.open() as file:
        return [row for row in csv.reader(file) if row and not row[0].startswith('#')]

def stamp(message, ns):
    message.header.stamp.sec, message.header.stamp.nanosec = divmod(ns, 10**9)

def main():
    wrapper_start=time.monotonic()
    parser=argparse.ArgumentParser()
    parser.add_argument('dataset',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--config',default='/ws/slam_benchmark/feature-sweep/configs/100/estimator_config.yaml')
    parser.add_argument('--frames',type=int,default=0)
    parser.add_argument('--stop-active-after',type=float,default=0)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    left=read_rows(args.dataset/'cam0/data.csv'); right=read_rows(args.dataset/'cam1/data.csv')
    imu=read_rows(args.dataset/'imu0/data.csv')
    assert len(left)==len(right) and all(a[0]==b[0] for a,b in zip(left,right))
    if args.frames:
        left=left[:args.frames];right=right[:args.frames]
        imu=[row for row in imu if int(row[0])<=int(left[-1][0])+20_000_000]
    cv2.setNumThreads(1)
    rclpy.init()
    node=rclpy.create_node('euroc_publisher_probe')
    image_qos=QoSProfile(depth=10,reliability=ReliabilityPolicy.RELIABLE,history=HistoryPolicy.KEEP_LAST)
    imu_qos=QoSProfile(depth=200,reliability=ReliabilityPolicy.BEST_EFFORT,history=HistoryPolicy.KEEP_LAST)
    pubs=[node.create_publisher(Image,f'/cam{k}/image_raw',image_qos) for k in (0,1)]
    imu_pub=node.create_publisher(Imu,'/imu0',imu_qos)
    lock=threading.Lock(); pose_count=0
    stock_pose_count=0
    stock_file=(args.output/'stock-pose-arrivals.csv').open('w')
    stock_writer=csv.writer(stock_file)
    stock_writer.writerow(['imu_timestamp_ns','arrival_monotonic_ns','px','py','pz','qw','qx','qy','qz'])
    def on_stock_pose(msg):
        nonlocal stock_pose_count
        now=time.monotonic_ns();p=msg.pose.pose.position;q=msg.pose.pose.orientation
        with lock:
            stock_writer.writerow([msg.header.stamp.sec*10**9+msg.header.stamp.nanosec,now,p.x,p.y,p.z,q.w,q.x,q.y,q.z]);stock_pose_count+=1
    stock_sub=node.create_subscription(PoseWithCovarianceStamped,'/poseimu',on_stock_pose,QoSProfile(depth=100,reliability=ReliabilityPolicy.RELIABLE))
    pose_file=(args.output/'pose-arrivals.csv').open('w')
    poses=csv.writer(pose_file); poses.writerow(['camera_timestamp_ns','arrival_monotonic_ns'])
    def on_pose(msg):
        nonlocal pose_count
        now=time.monotonic_ns()
        with lock:
            poses.writerow([msg.header.stamp.sec*10**9+msg.header.stamp.nanosec,now]);pose_count+=1
    pose_sub=node.create_subscription(PoseStamped,'/benchmark/pose_camera',on_pose,QoSProfile(depth=100,reliability=ReliabilityPolicy.RELIABLE))
    def spin_probe():
        try: rclpy.spin(node)
        except ExternalShutdownException: pass
    thread=threading.Thread(target=spin_probe,name='pose-probe')
    receiver_log=(args.output/'receiver.log').open('w')
    receiver=subprocess.Popen(['/ws/slam_benchmark/ros2-runner/build/ros_replay_receiver',args.config,str(args.output)],stdout=receiver_log,stderr=subprocess.STDOUT)
    thread.start()
    sent={'imu':0,'left':0,'right':0}; shutdown_mode='end_of_sequence'; stop_signal_ns=None; returncode=None
    exit_observed_ns=None; sent_at_signal=None
    try:
        deadline=time.monotonic()+30
        while min(p.get_subscription_count() for p in pubs)<1 or imu_pub.get_subscription_count()<1 or node.count_publishers('/benchmark/pose_camera')<1 or node.count_publishers('/poseimu')<1:
            if receiver.poll() is not None: raise RuntimeError(f'receiver exited before discovery: {receiver.returncode}')
            if time.monotonic()>deadline: raise RuntimeError('ROS discovery timeout')
            time.sleep(.1)
        time.sleep(.5)
        origin=int(left[0][0]); start=time.monotonic_ns()
        schedule=[(int(row[0]),0,index,row) for index,row in enumerate(imu)]
        schedule.extend((int(row[0]),1,index,row) for index,row in enumerate(left)); schedule.sort()
        with (args.output/'publish-events.csv').open('w') as file:
            writer=csv.writer(file);writer.writerow(['event','index','sensor_timestamp_ns','scheduled_monotonic_ns','begin_monotonic_ns','end_monotonic_ns'])
            for sensor_ns,kind,index,row in schedule:
                due=start+sensor_ns-origin
                remaining=(due-time.monotonic_ns())/1e9
                if remaining>0: time.sleep(remaining)
                if args.stop_active_after and stop_signal_ns is None and time.monotonic_ns()-start>=args.stop_active_after*1e9:
                    shutdown_mode='SIGINT_while_publisher_active'; stop_signal_ns=time.monotonic_ns();sent_at_signal=sent.copy();receiver.send_signal(signal.SIGINT)
                if stop_signal_ns and exit_observed_ns is None and receiver.poll() is not None:
                    exit_observed_ns=time.monotonic_ns()
                begin=time.monotonic_ns()
                if kind==0:
                    msg=Imu();stamp(msg,sensor_ns);msg.header.frame_id='imu0'
                    msg.angular_velocity.x,msg.angular_velocity.y,msg.angular_velocity.z=map(float,row[1:4])
                    msg.linear_acceleration.x,msg.linear_acceleration.y,msg.linear_acceleration.z=map(float,row[4:7])
                    imu_pub.publish(msg);sent['imu']+=1;event='imu'
                else:
                    for eye in (0,1):
                        name=(left if eye==0 else right)[index][1]
                        image=cv2.imread(str(args.dataset/f'cam{eye}/data'/name),cv2.IMREAD_GRAYSCALE)
                        if image is None or image.shape!=(480,752): raise RuntimeError(f'invalid image {name}')
                        msg=Image();stamp(msg,sensor_ns);msg.header.frame_id=f'cam{eye}'
                        msg.height,msg.width=image.shape;msg.encoding='mono8';msg.is_bigendian=0;msg.step=msg.width;msg.data=array.array('B',image.tobytes())
                        pubs[eye].publish(msg);sent['left' if eye==0 else 'right']+=1
                    event='pair'
                writer.writerow([event,index,sensor_ns,due,begin,time.monotonic_ns()])
                if kind==1 and index and index%400==0: print(f'PUBLISH_PROGRESS pairs={index+1}',flush=True)
        # Bounded quiet drain: establish that no more observed poses arrive, then stop.
        deadline=time.monotonic()+10; stable_since=time.monotonic(); previous=-1
        while time.monotonic()<deadline:
            with lock: current=pose_count
            if current!=previous: stable_since=time.monotonic();previous=current
            if time.monotonic()-stable_since>=2: break
            time.sleep(.1)
        if receiver.poll() is None:
            stop_signal_ns=time.monotonic_ns();receiver.send_signal(signal.SIGINT)
        try: returncode=receiver.wait(timeout=10)
        except subprocess.TimeoutExpired:
            receiver.kill();receiver.wait();raise RuntimeError('receiver failed to stop within 10 seconds')
        stop_complete_ns=exit_observed_ns or time.monotonic_ns()
        with lock: observed_poses=pose_count; observed_stock_poses=stock_pose_count
        metadata={'sent':sent,'sent_after_stop_signal':{k:sent[k]-sent_at_signal[k] for k in sent} if sent_at_signal else None,'dataset_stereo_pairs':len(left),'dataset_imu_samples':len(imu),'observed_poses':observed_poses,'receiver_exit_code':returncode,'shutdown_mode':shutdown_mode,'signal_to_exit_observed_ms':(stop_complete_ns-stop_signal_ns)/1e6 if stop_signal_ns else None,'origin_camera_timestamp_ns':origin,'start_monotonic_ns':start,'timing_clock':'Linux CLOCK_MONOTONIC via time.monotonic_ns / clock_gettime','image_qos':'reliable KeepLast 10','imu_publisher_qos':'best effort KeepLast 200','publisher_image_decode_threads':1,'ROS_DOMAIN_ID':os.environ.get('ROS_DOMAIN_ID'),'ROS_LOCALHOST_ONLY':os.environ.get('ROS_LOCALHOST_ONLY'),'RMW_IMPLEMENTATION':os.environ.get('RMW_IMPLEMENTATION'),'ground_truth_initialization':False,'physical_sensor_input':False}
        metadata['observed_stock_poseimu']=observed_stock_poses
        metadata['primary_pose_stream']='/poseimu, calibrated IMU stamp; nearest source camera association checked within 20 ms'
        metadata['diagnostic_probe_scope']='end of each IMU callback batch; may omit intermediate poses when one callback processes multiple queued cameras'
        receiver_metadata=json.loads((args.output/'receiver-summary.json').read_text())
        if receiver_metadata.get('owned_estimator_worker'):
            metadata['diagnostic_probe_scope']='camera-stamped pose after every processed camera on the owned estimator worker'
        elapsed=time.monotonic()-wrapper_start
        own=resource.getrusage(resource.RUSAGE_SELF); child=resource.getrusage(resource.RUSAGE_CHILDREN)
        metadata['resources']={'elapsed_including_startup_drain_stop_s':elapsed,'publisher_probe_cpu_percent':100*(own.ru_utime+own.ru_stime)/elapsed,'receiver_cpu_percent':100*(child.ru_utime+child.ru_stime)/elapsed,'publisher_probe_peak_rss_mib':own.ru_maxrss/1024,'receiver_peak_rss_mib':child.ru_maxrss/1024,'affinity_cpus':sorted(os.sched_getaffinity(0)),'cpu_units':'100 percent is one core'}
        (args.output/'replay-summary.json').write_text(json.dumps(metadata,indent=2))
        print(json.dumps(metadata),flush=True)
        if returncode!=0: raise RuntimeError(f'receiver exited {returncode}')
    finally:
        if receiver.poll() is None: receiver.send_signal(signal.SIGINT);receiver.wait(timeout=10)
        rclpy.shutdown();thread.join(timeout=5);node.destroy_node();pose_file.close();stock_file.close();receiver_log.close()

if __name__=='__main__':main()
