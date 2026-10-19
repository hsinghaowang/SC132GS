#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/ubuntu/sc132gs-kernel-sync-20261014
NAME=${1:?unique run name}
SECONDS_TO_RUN=${2:-90}
CONTROL=/sys/bus/platform/devices/acb3000.camss/fsync_control
systemctl stop sc132gs-camera-restore.service sc132gs-camera-rtsp.service
printf 'stop\n' > "$CONTROL"
printf 'start\n' > "$CONTROL"
trap 'printf "stop\n" > "$CONTROL"' EXIT
CAMERA_CPUS=$(python3 "$ROOT/camera_cpu_list.py")
taskset -c "$CAMERA_CPUS" python3 "$ROOT/collect_events.py" "$ROOT/$NAME-events" --seconds "$SECONDS_TO_RUN" &
observer=$!
CAM0=$(sc132gs-discover cam0)
CAM1=$(sc132gs-discover cam1)
if [[ ${3:-normal} == reverse ]]; then temporary=$CAM0; CAM0=$CAM1; CAM1=$temporary; fi
printf 'first=%s second=%s\n' "$CAM0" "$CAM1" > "$ROOT/$NAME-devices.txt"
set +e
taskset -c "$CAMERA_CPUS" "$ROOT/raw-sync-probe" "$CAM0" "$CAM1" "$ROOT/$NAME-raw" "$SECONDS_TO_RUN" > "$ROOT/$NAME.log" 2>&1
status=$?
set -e
if ((status != 0)); then kill -TERM "$observer" 2>/dev/null || true; fi
wait "$observer"
python3 "$ROOT/finalize_events.py" "$ROOT/$NAME-events"
printf '%s\n' "$status" > "$ROOT/$NAME-exit.txt"
dmesg --color=never > "$ROOT/$NAME-dmesg.txt"
exit "$status"
