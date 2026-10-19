#!/usr/bin/env bash
set -euo pipefail
OUT=/home/ubuntu/sc132gs-linear120-20261007
generator_pid=
capture_pid=
cleanup() {
    if [[ -n $capture_pid ]]; then kill "$capture_pid" 2>/dev/null || true; wait "$capture_pid" 2>/dev/null || true; fi
    if [[ -n $generator_pid ]]; then kill "$generator_pid" 2>/dev/null || true; wait "$generator_pid" 2>/dev/null || true; fi
    systemctl start sc132gs-hdr-rtsp 2>/dev/null ||
        systemd-run --unit=sc132gs-hdr-rtsp --property=Restart=on-failure \
        --setenv=BIND=192.168.137.226 --setenv=FPS=60 --setenv=BRIGHTNESS=40 --setenv=AUTO_EXPOSURE=1 \
        /bin/bash /home/ubuntu/stereo-h265-rtsp/run-stereo-rtsp.sh
}
trap cleanup EXIT INT TERM
sc132gs-ctl mode > "$OUT/before-mode.txt"
sc132gs-ctl status > "$OUT/before-status.txt"
systemctl cat sc132gs-hdr-rtsp > "$OUT/before-unit.txt"
systemctl stop sc132gs-hdr-rtsp
/usr/local/sbin/prepare-sc132gs-sync-gpios
media=$(sc132gs-discover media)
cam0=$(sc132gs-discover cam0)
cam1=$(sc132gs-discover cam1)
for entity in 'sc132gs 18-0032' 'sc132gs 16-0030'; do
    sensor=$(media-ctl -d "$media" -e "$entity")
    v4l2-ctl -d "$sensor" --get-ctrl=wide_dynamic_range | grep -q 'wide_dynamic_range: 0'
    v4l2-ctl -d "$sensor" --set-ctrl=exposure=500,analogue_gain=41
done
for rate in 60 120; do
    mkdir -p "$OUT/rate$rate"
    cd "$OUT/rate$rate"
    /usr/local/bin/sc132gs-fsync-generator auto 18 19 "$rate" 100 active-low > fsync.log 2>&1 &
    generator_pid=$!
    for ((attempt=0; attempt<100; ++attempt)); do
        grep -q 'FSYNC generator armed' fsync.log && break
        sleep 0.05
    done
    grep -q 'FSYNC generator armed' fsync.log
    kill -USR1 "$generator_pid"
    timeout 25 "$OUT/linear-rate-check" "$cam0" "$cam1" 600 500 120 > capture.log 2>&1 &
    capture_pid=$!
    for ((attempt=0; attempt<100; ++attempt)); do
        grep -q 'Both streams armed' capture.log && break
        sleep 0.01
    done
    grep -q 'Both streams armed' capture.log
    echo 1 > /sys/bus/i2c/devices/18-0032/trigger_60fps
    echo 1 > /sys/bus/i2c/devices/16-0030/trigger_60fps
    for spec in '18 0x32' '16 0x30'; do
        read -r bus addr <<< "$spec"
        for reg in 3018 3019 320c 320d 320e 320f 3222 3225 3e01 3e02 36e9 36f9 4837; do
            printf 'bus=%s addr=%s reg=%s value=' "$bus" "$addr" "$reg"
            i2ctransfer -f -y "$bus" "w2@$addr" "0x${reg:0:2}" "0x${reg:2:2}" r1
        done
    done > registers.txt
    set +e
    wait "$capture_pid"
    status=$?
    set -e
    capture_pid=
    echo "$status" > exit-status.txt
    kill "$generator_pid"; wait "$generator_pid" || true; generator_pid=
    echo "rate=$rate exit=$status"
    cat capture.log
    cat fsync.log
done
journalctl -k --since '-3 minutes' --no-pager > "$OUT/kernel.log"