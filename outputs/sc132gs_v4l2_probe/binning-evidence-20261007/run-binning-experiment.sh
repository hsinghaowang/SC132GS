#!/usr/bin/env bash
# Load the experiment sensor driver once, before first CAMSS registration.
# Never unload/reload qcom_camss on this kernel.
set -euo pipefail
ROOT=/home/ubuntu/sc132gs-binning-20261007
BASE=/home/ubuntu/stereo-h265-rtsp/linear120-profile
MODE=${1:-bin120}
[[ $EUID == 0 && $MODE =~ ^(full|bin120|bin60|rtspbin120|rtspbin60)$ ]] || exit 1
OUT=$ROOT/safe-$MODE
mkdir -p "$OUT"
find_media() {
    for candidate in /dev/media*; do
        if media-ctl -d "$candidate" -p 2>/dev/null | grep -q 'entity.*sc132gs 18-0032'; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}
if [[ ! -e /sys/module/sc132gs/parameters/experimental_half_format ]]; then
    [[ ! -e /sys/module/qcom_camss ]] || {
        echo 'Experiment module must be loaded before CAMSS; reboot required, no hot reload.' >&2
        exit 1
    }
    rmmod sc132gs
    insmod "$ROOT/sc132gs.ko" external_trigger=1 hdr=0 experimental_half_format=0
    modprobe qcom_camss
fi
capture_pid=
cleanup() {
    if [[ -n $capture_pid ]]; then kill "$capture_pid" 2>/dev/null || true; wait "$capture_pid" 2>/dev/null || true; fi
    printf 'N' > /sys/module/sc132gs/parameters/experimental_half_format
    MEDIA=$(find_media) bash /home/ubuntu/sc132gs-sync/configure-sc132gs-dual-pipeline.sh
    systemctl reset-failed sc132gs-hdr-rtsp sc132gs-linear120-rtsp 2>/dev/null || true
    systemctl start sc132gs-hdr-rtsp 2>/dev/null ||
        systemd-run --unit=sc132gs-hdr-rtsp --property=Restart=on-failure \
            --setenv=BIND=192.168.137.226 --setenv=FPS=60 --setenv=BRIGHTNESS=40 --setenv=AUTO_EXPOSURE=1 \
            /bin/bash /home/ubuntu/stereo-h265-rtsp/run-stereo-rtsp.sh
    # The accepted 60 FPS mode falls back to the original 60 FPS service.
    if [[ $MODE != rtspbin60 ]]; then
        systemd-run --unit=sc132gs-linear120-rtsp --property=TimeoutStopSec=15 \
            --setenv=PROFILE_DIR="$BASE" --setenv=DOWNSCALE=2 --setenv=DURATION_SECONDS=0 \
            --setenv=OUT=/home/ubuntu/stereo-h265-rtsp/rtsp120-restored-after-binning \
            /bin/bash /home/ubuntu/stereo-h265-rtsp/run-linear120-rtsp.sh
    fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM
systemctl stop sc132gs-linear120-rtsp 2>/dev/null || true
systemctl stop sc132gs-hdr-rtsp 2>/dev/null || true
# Changes below are only permitted after both capture owners are stopped.
if [[ $MODE == full ]]; then
    printf 'N' > /sys/module/sc132gs/parameters/experimental_half_format
    width=1088 height=1280
    MEDIA=$(find_media) bash /home/ubuntu/sc132gs-sync/configure-sc132gs-dual-pipeline.sh
else
    rate=120
    [[ $MODE != bin60 ]] || rate=60
    printf '%s' "$rate" > /sys/module/sc132gs/parameters/experimental_fps
    printf 'Y' > /sys/module/sc132gs/parameters/experimental_half_format
    width=544 height=640
    sed 's/1088x1280/544x640/g; s/width=1088,height=1280/width=544,height=640/g' \
        /home/ubuntu/sc132gs-sync/configure-sc132gs-dual-pipeline.sh > "$ROOT/configure-half.sh"
    MEDIA=$(find_media) bash "$ROOT/configure-half.sh"
fi
cam0=$(sc132gs-discover cam0)
cam1=$(sc132gs-discover cam1)
media-ctl -d "$(find_media)" -p > "$OUT/topology.txt"
cd "$OUT"
if [[ $MODE == rtspbin120 || $MODE == rtspbin60 ]]; then
    exposure_default=1000
    if [[ $MODE == rtspbin60 ]]; then
        # Keep the proven binning PLL/CSI timing; double VTS after STREAMON.
        # Sensor output geometry stays 544x640 throughout startup.
        rate=60
        exposure_default=2400
    fi
    "${SERVER_BIN:-/home/ubuntu/stereo-h265-rtsp/build-exposure60/stereo-h265-rtsp}" \
        --cam0 "$cam0" --cam1 "$cam1" --bind 192.168.137.226 --port 8554 \
        --mount /stereo --downscale 1 --fps "$rate" --auto-exposure off \
        --capture-mode "experimental-linear${rate}-binning" > server.log 2>&1 &
    capture_pid=$!
    armed=0
    for ((attempt=0;attempt<200;attempt++)); do
        if grep -q "Both $rate FPS receivers armed" server.log; then armed=1; break; fi
        kill -0 "$capture_pid" 2>/dev/null || break
        sleep 0.025
    done
    ((armed)) || { cat server.log; exit 1; }
    if [[ $MODE == rtspbin60 ]]; then
        for device in '18 0x32' '16 0x30'; do
            read -r bus address <<< "$device"
            i2ctransfer -f -y "$bus" "w3@$address" 0x32 0x0e 0x0a
            i2ctransfer -f -y "$bus" "w3@$address" 0x32 0x0f 0x8c
            read -r high low <<< "$(i2ctransfer -f -y "$bus" "w2@$address" 0x32 0x0e r2)"
            ((high*256+low == 2700)) || exit 1
            printf 'sensor=%s VTS=%s\n' "$address" 2700
        done > frame-timing.txt
    fi
    bash "$ROOT/set-binning-exposure.sh" "${EXPOSURE_ROWS:-$exposure_default}" > exposure-setting.txt
    if [[ -n ${GAIN_INDEX:-} ]]; then
        bash "$ROOT/set-binning-gain.sh" "$GAIN_INDEX" > gain-setting.txt
    fi
    if [[ ${AUTO_EXPOSURE:-0} == 1 ]]; then
        [[ $MODE == rtspbin60 ]] || exit 1
        # Enable only after VTS, exposure and gain have been applied/read back.
        sc132gs-ctl set-brightness "${AE_TARGET:-18}" > ae-enabled.txt
    fi
    deadline=$((SECONDS + ${DURATION_SECONDS:-40}))
    while kill -0 "$capture_pid" 2>/dev/null; do
        if ((${DURATION_SECONDS:-40} > 0 && SECONDS >= deadline)); then kill "$capture_pid"; break; fi
        sleep 1
    done
    status=0
    wait "$capture_pid" || status=$?
    capture_pid=
    cat server.log
else
    timeout 40 "$ROOT/raw-rate-check" "$cam0" 600 "$width" "$height" "$cam1" > capture.log 2>&1 &
    capture_pid=$!
    for ((n=0;n<200;n++)); do
        grep -q 'Stream armed' capture.log && break
        kill -0 "$capture_pid" || break
        sleep 0.025
    done
    grep -q 'Stream armed' capture.log || { cat capture.log; exit 1; }
    if [[ $MODE == full ]]; then
        for file in kendryte-120-registers.txt gs130wi-geometry-short-exposure.txt; do
            while read -r reg value; do
                i2ctransfer -f -y 18 w3@0x32 "0x${reg:2:2}" "0x${reg:4:2}" "$value"
                i2ctransfer -f -y 16 w3@0x30 "0x${reg:2:2}" "0x${reg:4:2}" "$value"
                [[ $reg != 0x0103 ]] || sleep 0.01
            done < "$BASE/$file"
        done
        i2ctransfer -f -y 18 w3@0x32 0x01 0x00 0x01
        i2ctransfer -f -y 16 w3@0x30 0x01 0x00 0x01
    fi
    for reg in 3208 3209 320a 320b 320c 320d 320e 320f 3220 3215 5000 5900 5901 3e00 3e01 3e02 3e08 3e09 36e9 36f9; do
        printf 'reg=%s value=' "$reg"
        i2ctransfer -f -y 18 w2@0x32 "0x${reg:0:2}" "0x${reg:2:2}" r1
    done > registers.txt
    status=0
    wait "$capture_pid" || status=$?
    capture_pid=
    cat capture.log
fi
dmesg > kernel.log
exit "$status"
