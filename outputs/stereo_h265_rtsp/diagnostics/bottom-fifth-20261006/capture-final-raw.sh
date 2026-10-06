#!/usr/bin/env bash
set -euo pipefail
OUT=/home/ubuntu/sc132gs-gate-fix-final
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
for camera in cam0 cam1; do
    node=$(/usr/local/sbin/sc132gs-discover "$camera")
    timeout 8 v4l2-ctl -d "$node" --stream-mmap=4 --stream-skip=8 --stream-count=3 \
        --stream-poll --stream-to="$OUT/$camera.raw"
    stat -c '%n %s bytes' "$OUT/$camera.raw"
done
