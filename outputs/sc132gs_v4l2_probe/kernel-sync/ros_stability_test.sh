#!/usr/bin/env bash
set -eo pipefail
source /opt/ros/humble/setup.bash
source /work/install-ros/share/gs130wi_ros/local_setup.bash
set -u
OUT=/stability/followup/ros
python3 /stability/verify_live.py --seconds 604 --minimum-active-seconds 590 \
  --maximum-gap-seconds 3 --output "$OUT/subscriber.json" > "$OUT/subscriber.log" 2>&1 &
verifier=$!
trap 'kill -TERM "$verifier" 2>/dev/null || true' EXIT
sleep 1
ros2 run gs130wi_ros gs130wi_publisher --ros-args -p downscale:=2 -p maximum_frames:=18000 \
  > "$OUT/publisher.log" 2>&1
wait "$verifier"
trap - EXIT
