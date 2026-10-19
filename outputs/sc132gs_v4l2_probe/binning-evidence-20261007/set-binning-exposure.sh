#!/usr/bin/env bash
# Explicit manual row exposure for the validated experimental binning mode.
set -euo pipefail
ROWS=${1:-1000}
[[ $EUID == 0 && $ROWS =~ ^[0-9]+$ ]] || exit 1
ROWS=$((10#$ROWS))
[[ $(cat /sys/module/sc132gs/parameters/experimental_half_format) == Y ]] || exit 1
RATE=$(cat /sys/module/sc132gs/parameters/experimental_fps)
[[ $RATE == 60 || $RATE == 120 ]] || exit 1
((ROWS >= 8 && ROWS <= 2560)) || { echo 'Supported control range: 8..2560 rows.' >&2; exit 1; }
# Resolve subdevices from sensor identity, not a fixed /dev/v4l-subdev number.
for client in 18-0032 16-0030; do
    [[ $(cat "/sys/bus/i2c/devices/$client/name") == sc132gs ]] || exit 1
    bus=${client%-*}
    address=0x${client#*-00}
    read -r stream <<< "$(i2ctransfer -f -y "$bus" "w2@$address" 0x01 0x00 r1)"
    [[ $stream == 0x01 ]] || { echo 'Sensor must already be streaming.' >&2; exit 1; }
    read -r high low <<< "$(i2ctransfer -f -y "$bus" "w2@$address" 0x32 0x0e r2)"
    ((ROWS <= high*256+low-8)) || exit 1
done
for client in 18-0032 16-0030; do
    nodes=(/sys/bus/i2c/devices/"$client"/video4linux/v4l-subdev*)
    ((${#nodes[@]} == 1)) && [[ -e ${nodes[0]} ]] || exit 1
    node=/dev/$(basename "${nodes[0]}")
    # The mode table overrides hardware after the driver cached controls.
    # Force a neighboring valid value first so requesting an already-cached
    # value cannot silently leave the sensor at the table's 256-row exposure.
    neighbor=$((ROWS > 8 ? ROWS-1 : ROWS+1))
    v4l2-ctl -d "$node" --set-ctrl="exposure=$neighbor"
    v4l2-ctl -d "$node" --set-ctrl="exposure=$ROWS"
    bus=${client%-*}
    address=0x${client#*-00}
    read -r high middle low <<< "$(i2ctransfer -f -y "$bus" "w2@$address" 0x3e 0x00 r3)"
    actual=$(((high & 15)*4096+middle*16+(low >> 4)))
    ((actual == ROWS)) || { echo "Exposure readback mismatch: $client $actual" >&2; exit 1; }
    printf 'sensor=%s exposure_rows=%s\n' "$client" "$actual"
done
