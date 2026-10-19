#!/usr/bin/env bash
set -eo pipefail
source /opt/ros/humble/setup.bash
source /work/install-ros/share/gs130wi_ros/local_setup.bash
set -u
python3 /work/outputs/gs130wi_ros/tools/verify_live.py --seconds 16 \
  --output /work/evidence/ros-subscriber.json > /work/evidence/ros-subscriber.log 2>&1 &
verifier=$!
trap 'kill "$verifier" 2>/dev/null || true' EXIT
sleep 1
ros2 run gs130wi_ros gs130wi_publisher --ros-args -p downscale:=2 -p maximum_frames:=360 \
  > /work/evidence/ros-publisher.log 2>&1
wait "$verifier"
trap - EXIT
