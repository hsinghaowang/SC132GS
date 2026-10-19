#!/usr/bin/env bash
set -e
source /opt/ros/humble/setup.bash
source /ws/slam_benchmark/openvins_ws/install/setup.bash
set -uo pipefail
export ROS_DOMAIN_ID=73 ROS_LOCALHOST_ONLY=1 RMW_IMPLEMENTATION=rmw_fastrtps_cpp
unset FASTRTPS_DEFAULT_PROFILES_FILE FASTDDS_DEFAULT_PROFILES_FILE
base=/ws/slam_benchmark
if [ "$5" != default ]; then export FASTRTPS_DEFAULT_PROFILES_FILE="$base/$5"; fi
# Arguments: dataset, output directory name, frames (0=full), prefetch, XML or default.
python3 "$base/ros-replay-native.py" "$base/datasets/$1/mav0" "$base/ros-results/$2" --frames "$3" --prefetch-pairs "$4"
