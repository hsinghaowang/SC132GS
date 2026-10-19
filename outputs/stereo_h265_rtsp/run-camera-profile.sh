#!/usr/bin/env bash
# This owner never starts another camera service from an EXIT trap.
set -euo pipefail
ROOT=/home/ubuntu/stereo-h265-rtsp
BIN=${SERVER_BIN:-$ROOT/build-main10/stereo-h265-rtsp}
HEVC_PROFILE=${HEVC_PROFILE:-main10}
LOG=/run/sc132gs-camera-server.log
READY=/run/sc132gs-camera-ready
if [[ -s $LOG ]]; then
    mkdir -p /home/ubuntu/sc132gs-camera-tests/startup-logs
    cp "$LOG" "/home/ubuntu/sc132gs-camera-tests/startup-logs/$(date +%s%N).log"
fi
# Clear readiness evidence before forking: the parent must never observe a
# previous process's idle-ready line before the child opens its redirected log.
: > "$LOG"
child=
demand=0
cleanup() {
    if [[ -n $child ]]; then kill "$child" 2>/dev/null || true; wait "$child" 2>/dev/null || true; fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM
if [[ $BINNING == 1 ]]; then
    cam0=$(sc132gs-discover cam0); cam1=$(sc132gs-discover cam1)
    "$BIN" --cam0 "$cam0" --cam1 "$cam1" --bind 192.168.137.226 --port 8554 \
        --mount /stereo --downscale 1 --fps "$FPS" --auto-exposure off \
        --capture-mode linear-binning --hevc-profile "$HEVC_PROFILE" > "$LOG" 2>&1 &
    child=$!
    armed=0
    for ((n=0;n<200;n++)); do
        if grep -q "Both $FPS FPS receivers armed" "$LOG"; then armed=1; break; fi
        kill -0 "$child" || break
        sleep 0.025
    done
    ((armed)) || exit 1
    divisor=1
    if ((FPS == 1)); then divisor=3; elif ((FPS == 2)); then divisor=2; fi
    rows_per_second=$((162000/divisor))
    # Round VTS up so the actual free-run cadence never exceeds the upper bound.
    vts=$(((rows_per_second+FPS-1)/FPS))
    ((vts <= 65535)) || exit 1
    for client in 18-0032 16-0030; do
        bus=${client%-*}; address=0x${client#*-00}
        if ((divisor > 1)); then
            read -r high low <<< "$(i2ctransfer -f -y "$bus" "w2@$address" 0x32 0x0c r2)"
            hts=$(((high*256+low)*divisor))
            ((hts <= 65535)) || exit 1
            i2ctransfer -f -y "$bus" "w3@$address" 0x32 0x0c "$((hts/256))"
            i2ctransfer -f -y "$bus" "w3@$address" 0x32 0x0d "$((hts%256))"
            read -r high low <<< "$(i2ctransfer -f -y "$bus" "w2@$address" 0x32 0x0c r2)"
            ((high*256+low == hts)) || exit 1
        fi
        i2ctransfer -f -y "$bus" "w3@$address" 0x32 0x0e "$((vts/256))"
        i2ctransfer -f -y "$bus" "w3@$address" 0x32 0x0f "$((vts%256))"
        read -r high low <<< "$(i2ctransfer -f -y "$bus" "w2@$address" 0x32 0x0e r2)"
        ((high*256+low == vts)) || exit 1
    done
    # Force hardware controls after the experiment table bypassed its cache.
    bash /home/ubuntu/sc132gs-binning-20261007/set-binning-exposure.sh 1000
    bash /home/ubuntu/sc132gs-binning-20261007/set-binning-gain.sh 0
else
    BIND=192.168.137.226 AUTO_EXPOSURE=0 SERVER_BIN="$BIN" HEVC_PROFILE="$HEVC_PROFILE" \
        bash "$ROOT/run-stereo-rtsp.sh" > "$LOG" 2>&1 &
    child=$!
    armed=0
    for ((n=0;n<200;n++)); do
        if grep -q 'capture_lifecycle phase=idle resources_released=1' "$LOG"; then demand=1; armed=1; break; fi
        if grep -q "Capture ready: fps=$FPS" "$LOG"; then armed=1; break; fi
        kill -0 "$child" || break
        sleep 0.025
    done
    ((armed)) || exit 1
    if ((demand == 0)); then sleep 1; fi
    # The high-rate trigger override initially installs the 60 FPS VTS.
    # Extend it for 31..59 before AE is enabled, so its exposure budget fits.
    if ((FPS > 30 && FPS < 60)) && [[ $SENSOR_MODE == linear ]]; then
        vts=$(((84000+FPS-1)/FPS))
        for client in 18-0032 16-0030; do
            bus=${client%-*}; address=0x${client#*-00}
            i2ctransfer -f -y "$bus" "w3@$address" 0x32 0x0e "$((vts/256))"
            i2ctransfer -f -y "$bus" "w3@$address" 0x32 0x0f "$((vts%256))"
            read -r high low <<< "$(i2ctransfer -f -y "$bus" "w2@$address" 0x32 0x0e r2)"
            ((high*256+low == vts)) || exit 1
        done
    fi
fi
# Timing setup starts in manual mode. Honor an explicit service AE preference
# only after the receivers and exposure budget are ready.
if [[ ${AUTO_EXPOSURE:-0} == 1 ]]; then
    flowing=$demand
    for ((attempt=0; attempt<200; ++attempt)); do
        if ((flowing)); then break; fi
        if grep -q '^input_fps=' "$LOG"; then flowing=1; break; fi
        kill -0 "$child" 2>/dev/null || break
        sleep 0.05
    done
    ((flowing)) || exit 1
    "${CTL:-/usr/local/bin/sc132gs-ctl}" set-brightness "${BRIGHTNESS:-30}"
fi
printf '%s\n' "$TOKEN" > "$READY"
wait "$child"
