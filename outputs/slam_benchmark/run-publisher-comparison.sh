#!/usr/bin/env bash
set -e
source /opt/ros/humble/setup.bash
source /ws/slam_benchmark/openvins_ws/install/setup.bash
set -uo pipefail
export ROS_DOMAIN_ID=73 ROS_LOCALHOST_ONLY=1 RMW_IMPLEMENTATION=rmw_fastrtps_cpp
base=/ws/slam_benchmark
check_core() {
  [ "$(sha256sum "$base/ros2-runner/build/ros_replay_receiver" | cut -d' ' -f1)" = 792c66116e2edddcb8877ec7fe488e29047dd38db28ea476306bc7722585b85f ]
  [ "$(sha256sum "$base/feature-sweep/configs/100/estimator_config.yaml" | cut -d' ' -f1)" = 92b82dce6932b3289c0cd7152068219b87e21c585419908f7ee3558e2b66ec10 ]
  [ "$(sha256sum "$base/ros-replay.py" | cut -d' ' -f1)" = 284927ae4e5e033005b417ce023d55ba4a62d013407828f77f72a82a4f21e489 ]
}
for case in 'MH_01_easy pubcontrol 1' 'MH_01_easy nativepub 1' 'V2_02_medium nativepub 1' 'V2_02_medium pubcontrol 1' 'MH_01_easy nativepub 2' 'V2_02_medium nativepub 2'; do
  read -r dataset variant repeat <<< "$case"
  check_core
  script=ros-replay.py
  [ "$variant" = nativepub ] && script=ros-replay-native.py
  echo "START $dataset $variant repeat=$repeat $(date -u +%FT%TZ)"
  python3 "$base/$script" "$base/datasets/$dataset/mav0" "$base/ros-results/$dataset-paced-$variant-$repeat"
  echo "DONE $dataset $variant repeat=$repeat $(date -u +%FT%TZ)"
done
echo PUBLISHER_COMPARISON_COMPLETE
