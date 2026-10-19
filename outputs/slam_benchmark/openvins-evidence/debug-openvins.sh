#!/usr/bin/env bash
set -eo pipefail
source /opt/ros/humble/setup.bash
workspace=/ws/slam_benchmark/openvins_ws
source "$workspace/install/setup.bash"
cd "$workspace"
export ROS_DOMAIN_ID=64 ROS_LOCALHOST_ONLY=1
gdb --batch -ex run -ex 'thread apply all bt 25' --args \
    "$workspace/install/ov_msckf/lib/ov_msckf/run_simulation" \
    "$workspace/src/open_vins/config/euroc_mav/estimator_config.yaml" \
    --ros-args -r __ns:=/slam_sim_debug \
    -p sim_freq_cam:=20.0 -p sim_freq_imu:=200.0 \
    -p sim_seed_state_init:=0 -p sim_seed_preturb:=0 -p sim_seed_measurements:=0 \
    -p sim_do_perturbation:=false -p sim_distance_threshold:=1.2 \
    -p sim_min_feature_gen_dist:=5.0 -p sim_max_feature_gen_dist:=10.0 \
    -p sim_traj_path:="$workspace/src/open_vins/ov_data/sim/udel_gore.txt" \
    -p verbosity:=INFO > evidence/simulation-backtrace.txt 2>&1
