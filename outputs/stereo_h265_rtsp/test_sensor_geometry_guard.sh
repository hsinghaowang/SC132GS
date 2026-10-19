#!/usr/bin/env bash
# Exercise sensor geometry with a fixed 1280-row DMA allocation.
# Restore sensor registers, guard setting and the camera service on every exit.
set -euo pipefail
OUT=${1:?output directory required}
GUARD=${2:?guard must be 0 or 1}
ROLE=${3:-cam0}
GEOMETRY=${4:-height}
DELTA=${5:-1}
case "$ROLE" in
    cam0) BUS=18; ADDRESS=0x32; CLIENT=18-0032; CSID_ID=0 ;;
    cam1) BUS=16; ADDRESS=0x30; CLIENT=16-0030; CSID_ID=1 ;;
    *) echo 'Expected cam0 or cam1' >&2; exit 2 ;;
esac
test "$GUARD" = 0 -o "$GUARD" = 1
case "$GEOMETRY:$DELTA" in
    height:1|height:-1|height:16) REG_LOW=0x0a; EXPECTED=1280 ;;
    *) echo 'Expected height +/-1/+16; sensor width expansion is not a valid fixture' >&2; exit 2 ;;
esac
mkdir "$OUT"
PARAM=/sys/module/qcom_camss/parameters
original_guard=$(cat "$PARAM/geometry_guard")
restore_was_active=$(systemctl is-active sc132gs-camera-restore.service || true)
rtsp_was_active=$(systemctl is-active sc132gs-camera-rtsp.service || true)
generator_pid= capture_pid= original_dimension=
cleanup() {
    local result=$?
    trap - EXIT
    if [[ -n $original_dimension && -n $capture_pid ]]; then
        i2ctransfer -f -y "$BUS" "w4@$ADDRESS" 0x32 "$REG_LOW" \
            "$((original_dimension / 256))" "$((original_dimension % 256))" \
            > "$OUT/register-restore.txt" 2>&1 || result=1
    fi
    if [[ -n $capture_pid ]]; then kill -TERM "$capture_pid" 2>/dev/null || true; wait "$capture_pid" 2>/dev/null || true; fi
    if [[ -n $generator_pid ]]; then kill -TERM "$generator_pid" 2>/dev/null || true; wait "$generator_pid" 2>/dev/null || true; fi
    echo "$original_guard" > "$PARAM/geometry_guard"
    if [[ $restore_was_active = active || $rtsp_was_active = active ]]; then
        systemctl start sc132gs-camera-restore.service > "$OUT/service-restore.txt" 2>&1 || result=1
        sc132gs-camera status >> "$OUT/service-restore.txt" 2>&1 || result=1
    fi
    exit "$result"
}
trap cleanup EXIT
systemctl stop sc132gs-camera-restore.service
systemctl stop sc132gs-camera-rtsp.service
if fuser /dev/video*; then echo 'Video device owned' >&2; exit 1; fi
VIDEO=$(sc132gs-discover "$ROLE")
echo "$GUARD" > "$PARAM/geometry_guard"
prepare-sc132gs-sync-gpios
sc132gs-fsync-generator auto 18 19 60 100 active-low > "$OUT/fsync.log" 2>&1 &
generator_pid=$!
for ((i=0;i<100;i++)); do
    grep -q 'FSYNC generator armed' "$OUT/fsync.log" && break
    sleep 0.01
done
grep -q 'FSYNC generator armed' "$OUT/fsync.log"
dmesg > "$OUT/dmesg-before.txt"
v4l2-ctl -d "$VIDEO" --get-fmt-video > "$OUT/format.txt"
timeout --signal=TERM --kill-after=3 8 v4l2-ctl -d "$VIDEO" \
    --stream-mmap=8 --stream-count=300 --stream-to=/dev/null \
    > "$OUT/capture.txt" 2>&1 &
capture_pid=$!
sleep 0.3
kill -0 "$capture_pid"
echo 1 > /sys/bus/i2c/devices/"$CLIENT"/trigger_60fps
kill -USR1 "$generator_pid"
sleep 0.5
read -r high low <<< "$(i2ctransfer -f -y "$BUS" "w2@$ADDRESS" 0x32 "$REG_LOW" r2)"
original_dimension=$((high*256+low))
test "$original_dimension" = "$EXPECTED"
injected=$((original_dimension+DELTA))
printf 'dimension=%s original=%d injected=%d\n' "$GEOMETRY" "$original_dimension" "$injected" > "$OUT/sensor-height.txt"
i2ctransfer -f -y "$BUS" "w4@$ADDRESS" 0x32 "$REG_LOW" "$((injected/256))" "$((injected%256))"
read -r high low <<< "$(i2ctransfer -f -y "$BUS" "w2@$ADDRESS" 0x32 "$REG_LOW" r2)"
printf 'readback=%d\n' "$((high*256+low))" >> "$OUT/sensor-height.txt"
test "$((high*256+low))" = "$injected"
sleep 0.2
capture_child=$(pgrep -P "$capture_pid")
python3 /home/ubuntu/camss-dma-fix-20261013/sample_csid_geometry.py \
    --csid "$CSID_ID" --capture-pid "$capture_child" > "$OUT/csid-after-injection.jsonl"
set +e
wait "$capture_pid"
RESULT=$?
set -e
capture_pid=
printf '%s\n' "$RESULT" > "$OUT/exit-code.txt"
dmesg > "$OUT/dmesg-after.txt"
echo "guard=$GUARD capture_exit=$RESULT"
exit "$RESULT"
