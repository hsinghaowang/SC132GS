#!/usr/bin/env bash
set -euo pipefail
OUT=/home/ubuntu/sc132gs-bottom-fifth-20261006
generator_pid=
cleanup() {
    if [[ -n $generator_pid ]]; then kill "$generator_pid" 2>/dev/null || true; wait "$generator_pid" 2>/dev/null || true; fi
    systemctl start sc132gs-hdr-rtsp 2>/dev/null ||
        systemd-run --unit=sc132gs-hdr-rtsp --property=Restart=on-failure \
        --setenv=BIND=192.168.137.226 --setenv=FPS=30 --setenv=BRIGHTNESS=40 \
        /bin/bash /home/ubuntu/stereo-h265-rtsp/run-stereo-rtsp.sh
}
trap cleanup EXIT
systemctl stop sc132gs-hdr-rtsp
/usr/local/sbin/prepare-sc132gs-sync-gpios
media=$(/usr/local/sbin/sc132gs-discover media)
sensor=$(media-ctl -d "$media" -e 'sc132gs 18-0032')
node=$(/usr/local/sbin/sc132gs-discover cam0)
v4l2-ctl -d "$sensor" --set-ctrl=exposure=2176,analogue_gain=55
for rate in 20 25 30; do
    /usr/local/bin/sc132gs-fsync-generator auto 18 19 "$rate" 100 active-low > "$OUT/fsync-rate$rate.log" 2>&1 &
    generator_pid=$!
    for ((attempt=0; attempt<100; ++attempt)); do
        grep -q 'FSYNC generator armed' "$OUT/fsync-rate$rate.log" && break
        sleep 0.05
    done
    grep -q 'FSYNC generator armed' "$OUT/fsync-rate$rate.log"
    kill -USR1 "$generator_pid"
    timeout 8 v4l2-ctl -d "$node" --stream-mmap=4 --stream-skip=24 --stream-count=3 \
        --stream-poll --stream-to="$OUT/cam0-rate$rate.raw"
    /home/ubuntu/stereo-h265-rtsp/build/bayer-luma-check "$OUT/cam0-rate$rate.raw" "$OUT/cam0-rate$rate.pgm"
    kill "$generator_pid"; wait "$generator_pid" || true; generator_pid=
done
