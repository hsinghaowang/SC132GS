#!/usr/bin/env bash
# Run only after the requested background camera/test workload has been paused.
set -e
source /opt/ros/humble/setup.bash
source /ws/slam_benchmark/openvins_ws/install/setup.bash
set -uo pipefail
export ROS_DOMAIN_ID=73 ROS_LOCALHOST_ONLY=1 RMW_IMPLEMENTATION=rmw_fastrtps_cpp
base=/ws/slam_benchmark
expected_binary=792c66116e2edddcb8877ec7fe488e29047dd38db28ea476306bc7722585b85f
expected_config=92b82dce6932b3289c0cd7152068219b87e21c585419908f7ee3558e2b66ec10
actual_binary=$(sha256sum "$base/ros2-runner/build/ros_replay_receiver" | cut -d' ' -f1)
actual_config=$(sha256sum "$base/feature-sweep/configs/100/estimator_config.yaml" | cut -d' ' -f1)
[ "$actual_binary" = "$expected_binary" ] && [ "$actual_config" = "$expected_config" ] || { echo HASH_MISMATCH; exit 1; }
for repeat in 1 2 3; do
  datasets="MH_01_easy V2_02_medium"
  [ "$repeat" = 2 ] && datasets="V2_02_medium MH_01_easy"
  for dataset in $datasets; do
    echo "START $dataset exclusive repeat=$repeat $(date -u +%FT%TZ)"
    python3 "$base/ros-replay.py" "$base/datasets/$dataset/mav0" "$base/ros-results/$dataset-paced-exclusive-$repeat"
    echo "DONE $dataset exclusive repeat=$repeat $(date -u +%FT%TZ)"
  done
done
echo EXCLUSIVE_COMPLETE
