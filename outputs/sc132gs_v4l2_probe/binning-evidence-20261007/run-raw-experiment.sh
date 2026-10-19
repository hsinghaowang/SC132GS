#!/usr/bin/env bash
set -euo pipefail
echo 'Obsolete diagnostic: CAMSS hot reload is unsafe. Use run-binning-experiment.sh.' >&2
exit 1
ROOT=/home/ubuntu/sc132gs-binning-20261007
BASE=/home/ubuntu/stereo-h265-rtsp/linear120-profile
MODE=${1:-full}
[[ $EUID == 0 && $MODE =~ ^(full|bin120|bin60|rtspbin120)$ ]] || exit 1
OUT=$ROOT/$MODE
mkdir -p "$OUT"
capture_pid=
module_changed=0
unbind_sensors() {
    for client in 18-0032 16-0030; do
        if [[ -e /sys/bus/i2c/drivers/sc132gs/$client ]]; then
            printf '%s' "$client" > /sys/bus/i2c/drivers/sc132gs/unbind
        fi
    done
}
stop_receiver() {
    for ((attempt=0;attempt<100;attempt++)); do
        [[ $(cat /sys/module/qcom_camss/refcnt) == 0 ]] && break
        sleep 0.1
    done
    rmmod qcom_camss
}
find_media() {
    for candidate in /dev/media*; do
        if media-ctl -d "$candidate" -p 2>/dev/null | grep -q 'entity.*sc132gs 18-0032'; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}
cleanup() {
    if [[ -n $capture_pid ]]; then kill "$capture_pid" 2>/dev/null || true; wait "$capture_pid" 2>/dev/null || true; fi
    if ((module_changed)); then
        unbind_sensors
        stop_receiver
        rmmod sc132gs
        modprobe qcom_camss
        modprobe sc132gs
        MEDIA=$(find_media) bash /home/ubuntu/sc132gs-sync/configure-sc132gs-dual-pipeline.sh
    fi
    systemctl start sc132gs-hdr-rtsp 2>/dev/null ||
        systemd-run --unit=sc132gs-hdr-rtsp --property=Restart=on-failure \
            --setenv=BIND=192.168.137.226 --setenv=FPS=60 --setenv=BRIGHTNESS=40 --setenv=AUTO_EXPOSURE=1 \
            /bin/bash /home/ubuntu/stereo-h265-rtsp/run-stereo-rtsp.sh
    systemctl reset-failed sc132gs-linear120-rtsp 2>/dev/null || true
    systemd-run --unit=sc132gs-linear120-rtsp --property=TimeoutStopSec=15 \
        --setenv=PROFILE_DIR="$BASE" --setenv=DOWNSCALE=2 --setenv=DURATION_SECONDS=0 \
        --setenv=OUT=/home/ubuntu/stereo-h265-rtsp/rtsp120-restored-after-binning \
        /bin/bash /home/ubuntu/stereo-h265-rtsp/run-linear120-rtsp.sh
}
trap cleanup EXIT
trap 'exit 130' INT TERM
systemctl stop sc132gs-linear120-rtsp 2>/dev/null || true
systemctl stop sc132gs-hdr-rtsp
width=1088 height=1280
if [[ $MODE != full ]]; then
    module_changed=1
    unbind_sensors
    stop_receiver
    rmmod sc132gs
    modprobe qcom_camss
    rate=120
    [[ $MODE != bin60 ]] || rate=60
    insmod "$ROOT/sc132gs.ko" external_trigger=1 hdr=0 experimental_half_format=1 experimental_fps="$rate"
    sed 's/1088x1280/544x640/g; s/width=1088,height=1280/width=544,height=640/g' \
        /home/ubuntu/sc132gs-sync/configure-sc132gs-dual-pipeline.sh > "$ROOT/configure-half.sh"
    MEDIA=$(find_media) bash "$ROOT/configure-half.sh"
    width=544 height=640
fi
cam0=$(sc132gs-discover cam0)
cam1=$(sc132gs-discover cam1)
media-ctl -d "$(find_media)" -p > "$OUT/topology.txt"
cd "$OUT"
if [[ $MODE == rtspbin120 ]]; then
    /home/ubuntu/stereo-h265-rtsp/build-binning/stereo-h265-rtsp \
        --cam0 "$cam0" --cam1 "$cam1" --bind 192.168.137.226 --port 8554 \
        --mount /stereo --downscale 1 --fps 120 --auto-exposure off \
        --capture-mode experimental-linear120-binning > server.log 2>&1 &
    capture_pid=$!
    deadline=$((SECONDS + ${DURATION_SECONDS:-40}))
    while kill -0 "$capture_pid" 2>/dev/null; do
        if ((${DURATION_SECONDS:-40} > 0 && SECONDS >= deadline)); then
            kill "$capture_pid"
            break
        fi
        sleep 1
    done
    status=0
    wait "$capture_pid" || status=$?
    capture_pid=
    cat server.log
    exit "$status"
fi
timeout 40 "$ROOT/raw-rate-check" "$cam0" 600 "$width" "$height" "$cam1" > capture.log 2>&1 &
capture_pid=$!
for ((n=0;n<200;n++)); do
    grep -q 'Stream armed' capture.log && break
    kill -0 "$capture_pid" || break
    sleep 0.025
done
grep -q 'Stream armed' capture.log || { cat capture.log; exit 1; }
apply() {
    while read -r reg value; do
        value=${value%$'\r'}
        [[ $reg =~ ^0x[0-9a-fA-F]{4}$ && $value =~ ^0x[0-9a-fA-F]{2}$ ]] || exit 1
        i2ctransfer -f -y 18 w3@0x32 "0x${reg:2:2}" "0x${reg:4:2}" "$value"
        i2ctransfer -f -y 16 w3@0x30 "0x${reg:2:2}" "0x${reg:4:2}" "$value"
        [[ $reg != 0x0103 ]] || sleep 0.01
    done < "$1"
}
if [[ $MODE == full ]]; then
    apply "$BASE/kendryte-120-registers.txt"
    apply "$BASE/gs130wi-geometry-short-exposure.txt"
fi
for reg in 3018 3019 3208 3209 320a 320b 320c 320d 320e 320f 3220 3215 5000 5900 5901 3e00 3e01 3e02 3e08 3e09 36e9 36f9 4837; do
    printf 'reg=%s value=' "$reg"
    i2ctransfer -f -y 18 w2@0x32 "0x${reg:0:2}" "0x${reg:2:2}" r1
done > registers.txt
if [[ $MODE == full ]]; then
    i2ctransfer -f -y 18 w3@0x32 0x01 0x00 0x01
    i2ctransfer -f -y 16 w3@0x30 0x01 0x00 0x01
fi
status=0
wait "$capture_pid" || status=$?
capture_pid=
journalctl -k --since '-2 minutes' --no-pager > kernel.log
cat capture.log
exit "$status"
