#!/usr/bin/env bash
set -e
source /opt/ros/humble/setup.bash
source /ws/slam_benchmark/openvins_ws/install/setup.bash
set -uo pipefail
base=/ws/slam_benchmark
config=$base/openvins_ws/src/open_vins/config/euroc_mav/estimator_config.yaml
dataset=$base/datasets/V2_02_medium/mav0
python3 "$base/verify-dataset.py" "$dataset"
sha256sum "$base/datasets/V2_02_medium.zip" > "$base/results/vicon2-inner-sha256.txt"
for mode in unpaced paced; do
  paced=0
  [ "$mode" = paced ] && paced=1
  for repeat in 1 2 3; do
    out=$base/results/V2_02_medium-$mode-$repeat
    python3 "$base/measure-run.py" "$out" "$base/euroc-runner/build/euroc_benchmark" "$config" "$dataset" "$out" "$paced" 0
  done
done
python3 "$base/evaluate-euroc.py" "$base/results" "$base/openvins_ws/src/open_vins/ov_data/euroc_mav/V2_02_medium.csv" V2_02_medium > "$base/results/vicon2-evaluation-output.json"
