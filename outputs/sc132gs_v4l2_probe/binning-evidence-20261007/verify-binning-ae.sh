#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/ubuntu/sc132gs-binning-20261007
OUT=$ROOT/ae60-validation
[[ $EUID == 0 ]] || exit 1
mkdir -p "$OUT"
restore() { sc132gs-ctl max-exposure-us 0 >/dev/null || true; sc132gs-ctl set-brightness 18 >/dev/null || true; }
trap restore EXIT
trace() {
    local phase=$1
    for ((n=0;n<24;n++)); do
        printf 'phase=%s uptime=' "$phase"
        cut -d' ' -f1 /proc/uptime
        sc132gs-ctl status
        sleep 0.25
    done >> "$OUT/control-trace.txt"
}
decode() {
    python3 "$ROOT/verify_decode_rate.py" rtsp://192.168.137.226:8554/stereo \
        --decoder software --seconds "$2" --output "$OUT/$1" > "$OUT/$1.log"
}
sc132gs-ctl status > "$OUT/start-status.txt"
# Produce an actually dark sensor image, then let the integrated AE recover.
sc132gs-ctl auto off > "$OUT/manual-dark-controls.txt"
bash "$ROOT/set-binning-exposure.sh" 300 >> "$OUT/manual-dark-controls.txt"
bash "$ROOT/set-binning-gain.sh" 0 >> "$OUT/manual-dark-controls.txt"
decode manual-dark 3
sc132gs-ctl set-brightness 18 >> "$OUT/manual-dark-controls.txt"
trace dark-recovery
decode recovered 6
# A changed target exercises exposure reduction without reducing frame rate.
sc132gs-ctl set-brightness 8 > "$OUT/low-target.txt"
trace lower-target
sc132gs-ctl status >> "$OUT/low-target.txt"
# Force an exposure ceiling so the gain-after-exposure path is exercised.
sc132gs-ctl set-brightness 18 > "$OUT/capped-controls.txt"
sc132gs-ctl max-exposure-us 1000 >> "$OUT/capped-controls.txt"
trace exposure-cap
sc132gs-ctl status >> "$OUT/capped-controls.txt"
sc132gs-ctl max-exposure-us 0 > "$OUT/final-controls.txt"
trace restore-ceiling
decode final 15
sc132gs-ctl status >> "$OUT/final-controls.txt"
for client in 18-0032 16-0030; do
    nodes=(/sys/bus/i2c/devices/"$client"/video4linux/v4l-subdev*)
    node=/dev/$(basename "${nodes[0]}")
    printf 'sensor=%s ' "$client"
    v4l2-ctl -d "$node" --get-ctrl=exposure,analogue_gain
    bus=${client%-*}; address=0x${client#*-00}
    printf 'exposure_registers='
    i2ctransfer -f -y "$bus" "w2@$address" 0x3e 0x00 r3
    printf 'gain_registers='
    i2ctransfer -f -y "$bus" "w2@$address" 0x3e 0x08 r2
done > "$OUT/final-readback.txt"
cat "$OUT/final-controls.txt" "$OUT/final/decode.json"
