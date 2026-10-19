#!/usr/bin/env bash
set -e
source /opt/ros/humble/setup.bash
source /ws/slam_benchmark/openvins_ws/install/setup.bash
set -uo pipefail
base=/ws/slam_benchmark
root=$base/feature-sweep
config=$root/configs/100/estimator_config.yaml
sha256sum "$config"
for repeat in 2 3; do
  datasets="MH_01_easy V2_02_medium"
  [ "$repeat" = 3 ] && datasets="V2_02_medium MH_01_easy"
  for dataset in $datasets; do
    out=$root/results/$dataset-pts100-paced-$repeat
    [ ! -e "$out" ] || { echo "Existing output: $out"; exit 1; }
    echo "START $dataset num_pts=100 repeat=$repeat $(date -u +%FT%TZ)"
    python3 "$base/measure-run.py" "$out" "$base/euroc-runner/build/euroc_benchmark" "$config" "$base/datasets/$dataset/mav0" "$out" 1 0
    echo "DONE $dataset num_pts=100 repeat=$repeat $(date -u +%FT%TZ)"
  done
done
echo CONFIRMATION_COMPLETE
