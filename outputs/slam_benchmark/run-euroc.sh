#!/usr/bin/env bash
set -e
source /opt/ros/humble/setup.bash
source /ws/slam_benchmark/openvins_ws/install/setup.bash
set -uo pipefail
base=/ws/slam_benchmark
config=$base/openvins_ws/src/open_vins/config/euroc_mav/estimator_config.yaml
dataset=$base/datasets/MH_01_easy/mav0
mkdir -p "$base/results"
sha256sum "$config" "${config%/*}"/kalibr* > "$base/results/config-sha256.txt"
uname -a > "$base/results/platform.txt"
cat /proc/cpuinfo >> "$base/results/platform.txt"
ps -eo comm,pcpu,pmem > "$base/results/concurrent-processes-before.txt"
for mode in unpaced paced; do
  paced=0
  [ "$mode" = paced ] && paced=1
  for repeat in 1 2 3; do
    out=$base/results/MH_01_easy-$mode-$repeat
    python3 "$base/measure-run.py" "$out" "$base/euroc-runner/build/euroc_benchmark" "$config" "$dataset" "$out" "$paced" 0
  done
done
