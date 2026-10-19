#!/usr/bin/env bash
set -e
source /opt/ros/humble/setup.bash
source /ws/slam_benchmark/openvins_ws/install/setup.bash
set -uo pipefail
export ROS_DOMAIN_ID=73 ROS_LOCALHOST_ONLY=1 RMW_IMPLEMENTATION=rmw_fastrtps_cpp
base=/ws/slam_benchmark
native_hash=$(sha256sum "$base/native-publisher/build/native_replay_publisher" | cut -d' ' -f1)
for case in 'MH_01_easy 1' 'V2_02_medium 1' 'V2_02_medium 2' 'MH_01_easy 2'; do
  read -r dataset repeat <<< "$case"
  [ "$(sha256sum "$base/ros2-runner/build/ros_replay_receiver" | cut -d' ' -f1)" = 792c66116e2edddcb8877ec7fe488e29047dd38db28ea476306bc7722585b85f ]
  [ "$(sha256sum "$base/feature-sweep/configs/100/estimator_config.yaml" | cut -d' ' -f1)" = 92b82dce6932b3289c0cd7152068219b87e21c585419908f7ee3558e2b66ec10 ]
  [ "$(sha256sum "$base/native-publisher/build/native_replay_publisher" | cut -d' ' -f1)" = "$native_hash" ]
  echo "START $dataset prefetch repeat=$repeat $(date -u +%FT%TZ)"
  python3 "$base/ros-replay-native.py" "$base/datasets/$dataset/mav0" "$base/ros-results/$dataset-paced-prefetch-$repeat" --prefetch-pairs 4
  echo "DONE $dataset prefetch repeat=$repeat $(date -u +%FT%TZ)"
done
echo PREFETCH_COMPLETE
