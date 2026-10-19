#!/usr/bin/env bash
set -e
source /opt/ros/humble/setup.bash
source /ws/slam_benchmark/openvins_ws/install/setup.bash
set -uo pipefail
export ROS_DOMAIN_ID=73 ROS_LOCALHOST_ONLY=1 RMW_IMPLEMENTATION=rmw_fastrtps_cpp
base=/ws/slam_benchmark
sha256sum "$base/ros2-runner/build/ros_replay_receiver" "$base/feature-sweep/configs/100/estimator_config.yaml"
for dataset in V2_02_medium MH_01_easy; do
  echo "START $dataset $(date -u +%FT%TZ)"
  python3 "$base/ros-replay.py" "$base/datasets/$dataset/mav0" "$base/ros-results/$dataset-paced-worker-1"
  echo "DONE $dataset $(date -u +%FT%TZ)"
done
echo ROS_FULL_COMPLETE
