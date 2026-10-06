#!/usr/bin/env bash
set -euo pipefail
OUT=/home/ubuntu/sc132gs-bottom-fifth-20261006
mkdir -p "$OUT"
generator_pid=
cleanup() {
    if [[ -n $generator_pid ]]; then
        kill "$generator_pid" 2>/dev/null || true
        wait "$generator_pid" 2>/dev/null || true
    fi
    systemctl start sc132gs-hdr-rtsp 2>/dev/null ||
        systemd-run --unit=sc132gs-hdr-rtsp --property=Restart=on-failure \
        --setenv=BIND=192.168.137.226 --setenv=FPS=30 --setenv=BRIGHTNESS=40 \
        /bin/bash /home/ubuntu/stereo-h265-rtsp/run-stereo-rtsp.sh
}
trap cleanup EXIT
sc132gs-ctl status > "$OUT/ae-before.txt"
systemctl stop sc132gs-hdr-rtsp
/usr/local/sbin/prepare-sc132gs-sync-gpios
/usr/local/bin/sc132gs-fsync-generator auto 18 19 30 100 active-low > "$OUT/fsync.log" 2>&1 &
generator_pid=$!
for ((attempt=0; attempt<100; ++attempt)); do
    grep -q 'FSYNC generator armed' "$OUT/fsync.log" && break
    sleep 0.05
done
grep -q 'FSYNC generator armed' "$OUT/fsync.log"
kill -USR1 "$generator_pid"
media=$(/usr/local/sbin/sc132gs-discover media)
for camera in cam0 cam1; do
    entity='sc132gs 18-0032'
    [[ $camera == cam1 ]] && entity='sc132gs 16-0030'
    sensor=$(media-ctl -d "$media" -e "$entity")
    node=$(/usr/local/sbin/sc132gs-discover "$camera")
    for gain in 0 54; do
        v4l2-ctl -d "$sensor" --set-ctrl=exposure=2176,analogue_gain="$gain"
        v4l2-ctl -d "$sensor" --get-ctrl=exposure,analogue_gain > "$OUT/$camera-gain$gain-controls.txt"
        timeout 8 v4l2-ctl -d "$node" --stream-mmap=4 --stream-skip=12 --stream-count=3 \
            --stream-poll --stream-to="$OUT/$camera-gain$gain.raw"
        /home/ubuntu/stereo-h265-rtsp/build/bayer-luma-check \
            "$OUT/$camera-gain$gain.raw" "$OUT/$camera-gain$gain.pgm"
    done
done
