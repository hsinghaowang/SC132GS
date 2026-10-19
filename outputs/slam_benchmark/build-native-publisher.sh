#!/usr/bin/env bash
set -e
source /opt/ros/humble/setup.bash
set -uo pipefail
cmake -S /ws/slam_benchmark/native-publisher -B /ws/slam_benchmark/native-publisher/build -DCMAKE_BUILD_TYPE=Release
cmake --build /ws/slam_benchmark/native-publisher/build -j 1
