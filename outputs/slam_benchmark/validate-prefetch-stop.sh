set -e
source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID=86 ROS_LOCALHOST_ONLY=1 RMW_IMPLEMENTATION=rmw_fastrtps_cpp
python3 /ws/slam_benchmark/validate-prefetch-stop.py