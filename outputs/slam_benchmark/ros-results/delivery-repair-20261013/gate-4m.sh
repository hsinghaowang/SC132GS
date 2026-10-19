source /opt/ros/humble/setup.bash
source /ws/slam_benchmark/openvins_ws/install/setup.bash
export ROS_DOMAIN_ID=73 ROS_LOCALHOST_ONLY=1 RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTRTPS_DEFAULT_PROFILES_FILE=/ws/slam_benchmark/fastdds-shm-4m.xml
python3 /ws/slam_benchmark/ros-replay-native-checked.py /ws/slam_benchmark/datasets/V2_02_medium/mav0 /ws/slam_benchmark/ros-results/V2_02_medium-paced-delivery-gate-4m --frames 600 --prefetch-pairs 4
