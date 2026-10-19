#!/usr/bin/env bash
set -e
source /opt/ros/humble/setup.bash
source /ws/slam_benchmark/openvins_ws/install/setup.bash
set -uo pipefail
python3 -c 'import rclpy,cv2; print("Python ROS/OpenCV available",cv2.__version__)'
cmake -S /ws/slam_benchmark/ros2-runner -B /ws/slam_benchmark/ros2-runner/build -DCMAKE_BUILD_TYPE=Release
cmake --build /ws/slam_benchmark/ros2-runner/build -j 1
