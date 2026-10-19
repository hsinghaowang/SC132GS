#!/usr/bin/env bash
set -euo pipefail
INDEX=${1:-0}
[[ $EUID == 0 && $INDEX =~ ^[0-9]+$ ]] || exit 1
INDEX=$((10#$INDEX))
# Restrict this experiment to the known LUT base gain steps.
case $INDEX in
    0) CODE=0320;;
    28) CODE=2320;;
    60) CODE=2720;;
    *) echo 'Supported gain indices: 0, 28, 60' >&2; exit 1;;
esac
[[ $(cat /sys/module/sc132gs/parameters/experimental_half_format) == Y ]] || exit 1
for client in 18-0032 16-0030; do
    [[ $(cat "/sys/bus/i2c/devices/$client/name") == sc132gs ]] || exit 1
    nodes=(/sys/bus/i2c/devices/"$client"/video4linux/v4l-subdev*)
    ((${#nodes[@]} == 1)) && [[ -e ${nodes[0]} ]] || exit 1
    node=/dev/$(basename "${nodes[0]}")
    bus=${client%-*}
    address=0x${client#*-00}
    [[ $(i2ctransfer -f -y "$bus" "w2@$address" 0x01 0x00 r1) == 0x01 ]] || exit 1
    v4l2-ctl -d "$node" --set-ctrl="analogue_gain=$((INDEX+1))"
    v4l2-ctl -d "$node" --set-ctrl="analogue_gain=$INDEX"
    read -r high low <<< "$(i2ctransfer -f -y "$bus" "w2@$address" 0x3e 0x08 r2)"
    actual=$(printf '%02x%02x' "$high" "$low")
    [[ $actual == "$CODE" ]] || { echo "Gain readback mismatch: $client $actual" >&2; exit 1; }
    printf 'sensor=%s gain_index=%s gain_code=0x%s\n' "$client" "$INDEX" "$actual"
    v4l2-ctl -d "$node" --get-ctrl=exposure,analogue_gain
done
