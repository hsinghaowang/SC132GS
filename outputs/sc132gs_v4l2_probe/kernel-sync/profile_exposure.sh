#!/usr/bin/env bash
# Record-only characterization; never writes durable camera settings.
set -euo pipefail
ROOT=/home/ubuntu/sc132gs-kernel-sync-20261014
NAME=${1:-exposure-boundaries-30hz}
test "$(cat /sys/module/qcom_camss/parameters/fsync_mode)" = 1
systemctl stop sc132gs-camera-restore.service sc132gs-camera-rtsp.service
# A short integration at the first STREAMON anchors the causal pulse; a pulse
# before sensor activation cannot be the first short-exposure frame's trigger.
for client in 18-0032 16-0030; do
    for node in /sys/bus/i2c/devices/$client/video4linux/v4l-subdev*; do
        v4l2-ctl -d "/dev/${node##*/}" --set-ctrl=exposure=8
    done
done
bash "$ROOT/run_raw_probe.sh" "$NAME" 175 &
capture=$!
trap 'kill -TERM "$capture" 2>/dev/null || true' EXIT
sleep 3
: > "$ROOT/$NAME-controls.txt"
for rows in 8 32 808 1330 1360 1377 8 1377; do
    python3 -c 'import time; print(time.monotonic_ns())' >> "$ROOT/$NAME-controls.txt"
    for client in 18-0032 16-0030; do
        for node in /sys/bus/i2c/devices/$client/video4linux/v4l-subdev*; do
            v4l2-ctl -d "/dev/${node##*/}" --set-ctrl="exposure=$rows"
            v4l2-ctl -d "/dev/${node##*/}" --get-ctrl=exposure >> "$ROOT/$NAME-controls.txt"
        done
    done
    sleep 20
done
wait "$capture"
trap - EXIT
