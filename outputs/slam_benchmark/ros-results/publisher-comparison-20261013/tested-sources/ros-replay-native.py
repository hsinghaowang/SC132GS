"""Native input publisher with the unchanged rclpy stock-pose timing endpoint."""
import argparse
import csv
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import threading
import time
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.qos import QoSProfile, ReliabilityPolicy
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped

def main():
    wrapper_start=time.monotonic()
    parser=argparse.ArgumentParser()
    parser.add_argument('dataset',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--frames',type=int,default=0)
    parser.add_argument('--config',default='/ws/slam_benchmark/feature-sweep/configs/100/estimator_config.yaml')
    args=parser.parse_args()
    if args.frames<0: parser.error('--frames must be nonnegative')
    args.output.mkdir(parents=True,exist_ok=False)
    rclpy.init()
    node=rclpy.create_node('euroc_publisher_probe')
    lock=threading.Lock();counts={'diagnostic':0,'stock':0}
    files=[];logs=[];receiver=None;publisher=None;thread=None
    try:
        diagnostic_file=(args.output/'pose-arrivals.csv').open('w');files.append(diagnostic_file)
        diagnostic=csv.writer(diagnostic_file);diagnostic.writerow(['camera_timestamp_ns','arrival_monotonic_ns'])
        stock_file=(args.output/'stock-pose-arrivals.csv').open('w');files.append(stock_file)
        stock=csv.writer(stock_file);stock.writerow(['imu_timestamp_ns','arrival_monotonic_ns','px','py','pz','qw','qx','qy','qz'])
        def on_pose(msg):
            now=time.monotonic_ns()
            with lock:
                diagnostic.writerow([msg.header.stamp.sec*10**9+msg.header.stamp.nanosec,now]);counts['diagnostic']+=1
        def on_stock(msg):
            now=time.monotonic_ns();p=msg.pose.pose.position;q=msg.pose.pose.orientation
            with lock:
                stock.writerow([msg.header.stamp.sec*10**9+msg.header.stamp.nanosec,now,p.x,p.y,p.z,q.w,q.x,q.y,q.z]);counts['stock']+=1
        qos=QoSProfile(depth=100,reliability=ReliabilityPolicy.RELIABLE)
        diagnostic_sub=node.create_subscription(PoseStamped,'/benchmark/pose_camera',on_pose,qos)
        stock_sub=node.create_subscription(PoseWithCovarianceStamped,'/poseimu',on_stock,qos)
        def spin_probe():
            try:rclpy.spin(node)
            except ExternalShutdownException:pass
        receiver_log=(args.output/'receiver.log').open('w');logs.append(receiver_log)
        receiver=subprocess.Popen(['/ws/slam_benchmark/ros2-runner/build/ros_replay_receiver',args.config,str(args.output)],stdout=receiver_log,stderr=subprocess.STDOUT)
        thread=threading.Thread(target=spin_probe,name='pose-probe');thread.start()
        deadline=time.monotonic()+30
        while (min(node.count_subscribers(t) for t in ('/imu0','/cam0/image_raw','/cam1/image_raw'))<1
               or node.count_publishers('/poseimu')<1 or node.count_publishers('/benchmark/pose_camera')<1):
            if receiver.poll() is not None:raise RuntimeError('receiver exited before discovery')
            if time.monotonic()>deadline:raise RuntimeError('receiver discovery timed out')
            time.sleep(.1)
        publisher_log=(args.output/'native-publisher.log').open('w');logs.append(publisher_log)
        publisher=subprocess.Popen(['/ws/slam_benchmark/native-publisher/build/native_replay_publisher',str(args.dataset),str(args.output),str(args.frames)],stdout=publisher_log,stderr=subprocess.STDOUT)
        # The datasets have historic stamps and a bounded 184 s maximum runtime here.
        deadline=time.monotonic()+300
        while publisher.poll() is None:
            if receiver.poll() is not None:raise RuntimeError('receiver exited during active publishing')
            if time.monotonic()>deadline:raise RuntimeError('native publisher timed out')
            time.sleep(.1)
        if publisher.returncode:raise RuntimeError(f'native publisher exited {publisher.returncode}')
        native=json.loads((args.output/'native-publisher-summary.json').read_text())
        deadline=time.monotonic()+10;stable_since=time.monotonic();previous=-1
        while time.monotonic()<deadline:
            with lock:current=counts['diagnostic']
            if current!=previous:stable_since=time.monotonic();previous=current
            if time.monotonic()-stable_since>=2:break
            time.sleep(.1)
        stop_signal_ns=time.monotonic_ns();receiver.send_signal(signal.SIGINT)
        returncode=receiver.wait(timeout=10);stop_complete_ns=time.monotonic_ns()
        with lock:observed=counts.copy()
        metadata=dict(sent=native['sent'],sent_after_stop_signal=None,
            dataset_stereo_pairs=native['dataset_stereo_pairs'],dataset_imu_samples=native['dataset_imu_samples'],
            observed_poses=observed['diagnostic'],observed_stock_poseimu=observed['stock'],
            receiver_exit_code=returncode,shutdown_mode='end_of_sequence',
            signal_to_exit_observed_ms=(stop_complete_ns-stop_signal_ns)/1e6,
            origin_camera_timestamp_ns=native['origin_camera_timestamp_ns'],start_monotonic_ns=native['start_monotonic_ns'],
            timing_clock='Linux CLOCK_MONOTONIC via clock_gettime / time.monotonic_ns',
            image_qos='reliable KeepLast 10',imu_publisher_qos='best effort KeepLast 200',
            publisher_image_decode_threads=1,publisher_implementation='C++17 rclcpp; PNG decode on scheduled publication path; no preloading',
            ROS_DOMAIN_ID=os.environ.get('ROS_DOMAIN_ID'),ROS_LOCALHOST_ONLY=os.environ.get('ROS_LOCALHOST_ONLY'),
            RMW_IMPLEMENTATION=os.environ.get('RMW_IMPLEMENTATION'),ground_truth_initialization=False,physical_sensor_input=False,
            primary_pose_stream='/poseimu, calibrated IMU stamp; nearest source camera association checked within 20 ms',
            diagnostic_probe_scope='camera-stamped pose after every processed camera on the owned estimator worker',
            publisher_exit_code=publisher.returncode,native_publisher_summary=native)
        elapsed=time.monotonic()-wrapper_start
        own=resource.getrusage(resource.RUSAGE_SELF);child=resource.getrusage(resource.RUSAGE_CHILDREN)
        metadata['resources']=dict(elapsed_including_startup_drain_stop_s=elapsed,
            publisher_probe_cpu_percent=100*(own.ru_utime+own.ru_stime+native['cpu_seconds'])/elapsed,
            receiver_cpu_percent=100*(child.ru_utime+child.ru_stime-native['cpu_seconds'])/elapsed,
            publisher_probe_peak_rss_mib=max(own.ru_maxrss/1024,native['peak_rss_mib']),
            receiver_peak_rss_mib=child.ru_maxrss/1024,
            affinity_cpus=sorted(os.sched_getaffinity(0)),cpu_units='100 percent is one logical core',
            accounting='publisher includes native input process and rclpy probe; receiver CPU subtracts native self CPU from waited children; child peak RSS is aggregate maximum')
        (args.output/'replay-summary.json').write_text(json.dumps(metadata,indent=2))
        print(json.dumps(metadata),flush=True)
        if returncode:raise RuntimeError(f'receiver exited {returncode}')
    finally:
        for process in (publisher,receiver):
            if process is not None and process.poll() is None:
                process.send_signal(signal.SIGINT)
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait()
        rclpy.shutdown()
        if thread is not None:
            thread.join(timeout=5)
            if thread.is_alive():raise RuntimeError('pose probe did not stop')
        node.destroy_node()
        for file in files+logs:file.close()

if __name__=='__main__':main()
