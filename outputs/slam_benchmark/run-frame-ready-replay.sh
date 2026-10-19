#!/usr/bin/env bash
# Dataset-only measurement from scheduled, already-decoded images to stock pose.
# Set a process-local SHM capacity and require complete receiver input counts.
set -e
source /opt/ros/humble/setup.bash
source /ws/slam_benchmark/openvins_ws/install/setup.bash
set -uo pipefail
if [ "$#" -ne 2 ]; then echo 'usage: run-frame-ready-replay.sh dataset/mav0 new-output-directory' >&2; exit 2; fi
export ROS_DOMAIN_ID=73 ROS_LOCALHOST_ONLY=1 RMW_IMPLEMENTATION=rmw_fastrtps_cpp
unset FASTDDS_DEFAULT_PROFILES_FILE
export FASTRTPS_DEFAULT_PROFILES_FILE=/ws/slam_benchmark/fastdds-shm-4m.xml
python3 /ws/slam_benchmark/ros-replay-native-checked.py "$1" "$2" --prefetch-pairs 4
