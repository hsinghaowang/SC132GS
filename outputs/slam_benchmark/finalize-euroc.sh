#!/usr/bin/env bash
set -e
source /opt/ros/humble/setup.bash
source /ws/slam_benchmark/openvins_ws/install/setup.bash
set -uo pipefail
base=/ws/slam_benchmark
result=$base/results
python3 "$base/verify-evaluation.py" > "$result/evaluation-check.txt"
python3 "$base/evaluate-euroc.py" "$result" "$base/openvins_ws/src/open_vins/ov_data/euroc_mav/MH_01_easy.csv" > "$result/mhall-evaluation-output.json"
python3 "$base/make-euroc-report.py" "$result"
cp "$base/benchmark-conditions.json" "$base/dataset-provenance.json" "$result/"
cp "$base/datasets/MH_01_easy/mav0/verified.json" "$result/MH_01_easy-input-verified.json"
cp "$base/datasets/V2_02_medium/mav0/verified.json" "$result/V2_02_medium-input-verified.json"
cp "$base/datasets/checksum.txt" "$base/datasets/checksum-vicon2.txt" "$result/"
"$base/bag-tools/bin/pip" freeze --local > "$result/bag-tools-versions.txt"
dpkg-query -W python3-pip python3-venv python3.10-venv libopencv-dev libceres-dev libeigen3-dev libboost-system-dev libboost-filesystem-dev libboost-thread-dev libboost-date-time-dev > "$result/package-versions.txt"
g++ --version > "$result/compiler.txt"
git -C "$base/openvins_ws/src/open_vins" rev-parse HEAD > "$result/revision.txt"
git -C "$base/openvins_ws/src/open_vins" diff --binary > "$result/upstream-patch.diff"
sha256sum "$base/euroc-runner/main.cpp" "$base/euroc-runner/CMakeLists.txt" "$base/openvins_ws/src/open_vins/ov_data/euroc_mav/MH_01_easy.csv" "$base/openvins_ws/src/open_vins/ov_data/euroc_mav/V2_02_medium.csv" > "$result/source-and-groundtruth-sha256.txt"
cd "$result"
find . -type f ! -name evidence.sha256 -print0 | sort -z | xargs -0 sha256sum > evidence.sha256
