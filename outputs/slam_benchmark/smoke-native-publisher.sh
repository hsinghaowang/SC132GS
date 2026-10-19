set -e
source /opt/ros/humble/setup.bash
source /ws/slam_benchmark/openvins_ws/install/setup.bash
export ROS_DOMAIN_ID=73 ROS_LOCALHOST_ONLY=1 RMW_IMPLEMENTATION=rmw_fastrtps_cpp
python3 /ws/slam_benchmark/ros-replay-native.py /ws/slam_benchmark/datasets/V2_02_medium/mav0 /ws/slam_benchmark/ros-results/V2_02_medium-paced-nativepub-smoke --frames 240