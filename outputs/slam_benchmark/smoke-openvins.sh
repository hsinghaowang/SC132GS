#!/usr/bin/env bash
set -eo pipefail
source /opt/ros/humble/setup.bash
workspace=/ws/slam_benchmark/openvins_ws
source "$workspace/install/setup.bash"
set -u
cd "$workspace"
config="$workspace/src/open_vins/config/euroc_mav/estimator_config.yaml"
export ROS_DOMAIN_ID=64
export ROS_LOCALHOST_ONLY=1
ros2 pkg executables ov_msckf | tee evidence/executables.txt
set +e
timeout --signal=INT --kill-after=5s 8s \
    ros2 run ov_msckf run_subscribe_msckf "$config" \
    --ros-args -r __ns:=/slam_smoke -p verbosity:=INFO -p multi_threading_pubs:=false \
    > evidence/subscriber-startup.txt 2>&1
startup_status=$?
set -e
if [[ "$startup_status" != 124 ]]; then
    cat evidence/subscriber-startup.txt
    printf 'Unexpected subscriber startup exit: %s\n' "$startup_status" >&2
    exit 1
fi
grep -q 'subscribing to' evidence/subscriber-startup.txt
if grep -Eq 'Segmentation fault|Aborted|Assertion|Error in destruction|Failed to delete' evidence/subscriber-startup.txt; then
    printf 'Subscriber shutdown failed; see evidence/subscriber-startup.txt\n' >&2
    exit 1
fi
# Synthetic feature coordinates and synthetic IMU only. This does NOT run
# the real image tracker, validate the board cameras, or benchmark image FPS.
timeout --signal=INT --kill-after=5s 180s \
    ros2 run ov_msckf run_simulation "$config" \
    --ros-args -r __ns:=/slam_sim_smoke \
    -p sim_freq_cam:=20.0 -p sim_freq_imu:=200.0 \
    -p sim_seed_state_init:=0 -p sim_seed_preturb:=0 -p sim_seed_measurements:=0 \
    -p sim_do_perturbation:=false -p sim_distance_threshold:=1.2 \
    -p sim_min_feature_gen_dist:=5.0 -p sim_max_feature_gen_dist:=10.0 \
    -p sim_traj_path:="$workspace/src/open_vins/ov_data/sim/udel_gore.txt" \
    -p verbosity:=INFO \
    > evidence/simulation.txt 2>&1
grep -q 'RMSE:' evidence/simulation.txt
printf 'Subscriber startup and complete synthetic estimator simulation passed.\n'
