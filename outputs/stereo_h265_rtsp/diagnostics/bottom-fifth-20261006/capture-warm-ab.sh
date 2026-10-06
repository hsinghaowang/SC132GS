#!/usr/bin/env bash
set -euo pipefail
OUT=/home/ubuntu/sc132gs-bottom-fifth-20261006
generator_pid=
capture_pid=
cleanup() {
    if [[ -n $capture_pid ]]; then kill "$capture_pid" 2>/dev/null || true; wait "$capture_pid" 2>/dev/null || true; fi
    if [[ -n $generator_pid ]]; then kill "$generator_pid" 2>/dev/null || true; wait "$generator_pid" 2>/dev/null || true; fi
    systemctl start sc132gs-hdr-rtsp 2>/dev/null ||
        systemd-run --unit=sc132gs-hdr-rtsp --property=Restart=on-failure \
        --setenv=BIND=192.168.137.226 --setenv=FPS=30 --setenv=BRIGHTNESS=40 \
        /bin/bash /home/ubuntu/stereo-h265-rtsp/run-stereo-rtsp.sh
}
trap cleanup EXIT
systemctl stop sc132gs-hdr-rtsp
/usr/local/sbin/prepare-sc132gs-sync-gpios
/usr/local/bin/sc132gs-fsync-generator auto 18 19 30 100 active-low > "$OUT/fsync-trigger.log" 2>&1 &
generator_pid=$!
for ((attempt=0; attempt<100; ++attempt)); do
    grep -q 'FSYNC generator armed' "$OUT/fsync-trigger.log" && break
    sleep 0.05
done
grep -q 'FSYNC generator armed' "$OUT/fsync-trigger.log"
kill -USR1 "$generator_pid"
media=$(/usr/local/sbin/sc132gs-discover media)
for camera in cam0 cam1; do
    entity='sc132gs 18-0032'; bus=18; addr=0x32
    if [[ $camera == cam1 ]]; then entity='sc132gs 16-0030'; bus=16; addr=0x30; fi
    sensor=$(media-ctl -d "$media" -e "$entity")
    node=$(/usr/local/sbin/sc132gs-discover "$camera")
    v4l2-ctl -d "$sensor" --set-ctrl=exposure=2176,analogue_gain=55
    for mode in warm; do
        timeout 8 v4l2-ctl -d "$node" --stream-mmap=4 --stream-skip=90 --stream-count=3 \
            --stream-poll --stream-to="$OUT/$camera-trigger-$mode.raw" > "$OUT/$camera-trigger-$mode.log" 2>&1 &
        capture_pid=$!
        if [[ $mode == warm ]]; then
            ready=0
            for ((attempt=0; attempt<100; ++attempt)); do
                value=$(i2ctransfer -f -y "$bus" "w2@$addr" 0x01 0x00 r1)
                if [[ $value == 0x01 ]]; then ready=1; break; fi
                sleep 0.01
            done
            (( ready == 1 ))
            # Preserve HDR bits; compare only external-trigger slave versus free-run.
            i2ctransfer -f -y "$bus" "w3@$addr" 0x32 0x22 0x30
            sleep 1; i2ctransfer -f -y "$bus" "w3@$addr" 0x32 0x22 0x32; i2ctransfer -f -y "$bus" "w2@$addr" 0x32 0x22 r1
        fi
        wait "$capture_pid"
        capture_pid=
        stat -c '%n %s bytes' "$OUT/$camera-trigger-$mode.raw"
        /home/ubuntu/stereo-h265-rtsp/build/bayer-luma-check "$OUT/$camera-trigger-$mode.raw" "$OUT/$camera-trigger-$mode.pgm"
    done
done
