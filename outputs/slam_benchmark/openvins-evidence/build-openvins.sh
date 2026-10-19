#!/usr/bin/env bash
set -eo pipefail
source /opt/ros/humble/setup.bash
set -u
workspace=/ws/slam_benchmark/openvins_ws
revision=69488123ed9362dd44b6f28e7f4680abbff1442b
lifecycle_patch="$(cd "$(dirname "$0")" && pwd)/ros2-lifecycle.patch"
if [[ ! -f "$lifecycle_patch" ]]; then
    lifecycle_patch="$workspace/evidence/ros2-lifecycle.patch"
fi
test -f "$lifecycle_patch"
mkdir -p "$workspace/src" "$workspace/evidence"
cd "$workspace"
if [[ ! -d src/open_vins ]]; then
    git clone https://github.com/rpng/open_vins.git src/open_vins
fi
if [[ -z "$(git -C src/open_vins status --porcelain)" ]]; then
    git -C src/open_vins checkout --detach "$revision"
    git -C src/open_vins apply "$lifecycle_patch"
else
    # Accept only this exact recorded patch, preserving any unrelated changes.
    git -C src/open_vins diff --binary | cmp - "$lifecycle_patch"
    test -z "$(git -C src/open_vins ls-files --others --exclude-standard)"
fi
test "$(git -C src/open_vins rev-parse HEAD)" = "$revision"
git -C src/open_vins rev-parse HEAD > evidence/revision.txt
cp "$lifecycle_patch" evidence/applied-lifecycle.patch
colcon build --packages-select ov_core ov_init ov_msckf \
    --executor sequential --event-handlers console_cohesion+ \
    --cmake-args -DCMAKE_BUILD_TYPE=Release -DENABLE_ARUCO_TAGS=OFF \
    -DDISABLE_MATPLOTLIB=ON -DBUILD_TESTING=OFF \
    2>&1 | tee evidence/build.txt
