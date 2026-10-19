#!/usr/bin/env bash
set -e
source /opt/ros/humble/setup.bash
source /ws/slam_benchmark/openvins_ws/install/setup.bash
set -uo pipefail
export ROS_DOMAIN_ID=73 ROS_LOCALHOST_ONLY=1 RMW_IMPLEMENTATION=rmw_fastrtps_cpp
base=/ws/slam_benchmark
python3 "$base/ros-replay.py" "$base/datasets/V2_02_medium/mav0" "$base/ros-results/smoke-active-worker" --frames 240 --stop-active-after 9
