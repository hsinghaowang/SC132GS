#!/usr/bin/env bash
set -euo pipefail
OUT=/home/ubuntu/sc132gs-bottom-fifth-20261006
generator_pid=
media=$(/usr/local/sbin/sc132gs-discover media)
csid0=$(media-ctl -d "$media" -e msm_csid0)
csid1=$(media-ctl -d "$media" -e msm_csid1)
node0=$(/usr/local/sbin/sc132gs-discover cam0)
node1=$(/usr/local/sbin/sc132gs-discover cam1)
cleanup() {
    v4l2-ctl -d "$csid0" --set-ctrl=test_pattern=0 || true
    v4l2-ctl -d "$csid1" --set-ctrl=test_pattern=0 || true
    /usr/local/sbin/configure-sc132gs-dual-pipeline
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
systemctl stop sc132gs-hdr-rtsp
media-ctl -d "$media" -l '"msm_csiphy1":1->"msm_csid0":0[0]'
media-ctl -d "$media" -l '"msm_csiphy4":1->"msm_csid1":0[0]'
/usr/local/sbin/prepare-sc132gs-sync-gpios
/usr/local/bin/sc132gs-fsync-generator auto 18 19 30 100 active-low > "$OUT/fsync-pattern.log" 2>&1 &
generator_pid=$!
for ((attempt=0; attempt<100; ++attempt)); do
    grep -q 'FSYNC generator armed' "$OUT/fsync-pattern.log" && break
    sleep 0.05
done
grep -q 'FSYNC generator armed' "$OUT/fsync-pattern.log"
kill -USR1 "$generator_pid"
for camera in cam0 cam1; do
    csid=$csid0
    node=$node0
    if [[ $camera == cam1 ]]; then csid=$csid1; node=$node1; fi
    for pattern in 1 9; do
        v4l2-ctl -d "$csid" --set-ctrl=test_pattern="$pattern"
        timeout 8 v4l2-ctl -d "$node" --stream-mmap=4 --stream-skip=2 --stream-count=1 \
            --stream-poll --stream-to="$OUT/$camera-csid$pattern.raw"
    done
    v4l2-ctl -d "$csid" --set-ctrl=test_pattern=0
done
