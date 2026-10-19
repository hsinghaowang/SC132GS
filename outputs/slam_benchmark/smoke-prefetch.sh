set -e
source /opt/ros/humble/setup.bash
source /ws/slam_benchmark/openvins_ws/install/setup.bash
export ROS_DOMAIN_ID=85 ROS_LOCALHOST_ONLY=1 RMW_IMPLEMENTATION=rmw_fastrtps_cpp
python3 /ws/slam_benchmark/validate-prefetch-payload.py
export ROS_DOMAIN_ID=73
python3 /ws/slam_benchmark/ros-replay-native.py /ws/slam_benchmark/datasets/V2_02_medium/mav0 /ws/slam_benchmark/ros-results/V2_02_medium-paced-prefetch-smoke --frames 240 --prefetch-pairs 4