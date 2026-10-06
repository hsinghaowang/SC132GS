#!/usr/bin/env bash
set -euo pipefail
OUT=/home/ubuntu/sc132gs-bottom-fifth-20261006
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
systemctl stop sc132gs-hdr-rtsp 2>/dev/null || true
/usr/local/sbin/prepare-sc132gs-sync-gpios
/usr/local/bin/sc132gs-fsync-generator auto 18 19 30 100 active-low > "$OUT/fsync-fixed.log" 2>&1 &
generator_pid=$!
for ((attempt=0; attempt<100; ++attempt)); do
    grep -q 'FSYNC generator armed' "$OUT/fsync-fixed.log" && break
    sleep 0.05
done
grep -q 'FSYNC generator armed' "$OUT/fsync-fixed.log"
kill -USR1 "$generator_pid"
/home/ubuntu/stereo-h265-rtsp/build/stereo-capture-check 600 30 | tee "$OUT/capture-gate-final.txt"
