#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/ubuntu/sc132gs-linear120-20261007
OUT=$ROOT/kendryte-dual
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
mkdir -p "$OUT"
sc132gs-ctl mode | tee "$OUT/before-mode.txt"
grep -q 'camera_mode=linear' "$OUT/before-mode.txt"
systemctl stop sc132gs-hdr-rtsp
/usr/local/sbin/prepare-sc132gs-sync-gpios
cam0=$(sc132gs-discover cam0)
cam1=$(sc132gs-discover cam1)
for spec in 'free 120' 'trigger 100' 'trigger 120'; do
    read -r mode rate <<< "$spec"
    mkdir -p "$OUT/$mode$rate"
    cd "$OUT/$mode$rate"
    if [[ $mode == trigger ]]; then
        /usr/local/bin/sc132gs-fsync-generator auto 18 19 "$rate" 100 active-low > fsync.log 2>&1 &
        generator_pid=$!
        for ((attempt=0; attempt<100; ++attempt)); do
            grep -q 'FSYNC generator armed' fsync.log && break
            sleep 0.05
        done
        grep -q 'FSYNC generator armed' fsync.log
    fi
    timeout 35 "$ROOT/dual-profile-check" "$cam0" "$cam1" 1200 500 120 > capture.log 2>&1 &
    capture_pid=$!
    for ((attempt=0; attempt<100; ++attempt)); do
        grep -q 'Both streams armed' capture.log && break
        sleep 0.01
    done
    grep -q 'Both streams armed' capture.log
    for device in '18 0x32' '16 0x30'; do
        read -r bus addr <<< "$device"
        files=("$ROOT/kendryte-120-registers.txt" "$ROOT/gs130wi-geometry-short-exposure.txt")
        if [[ $mode == trigger ]]; then files+=("$ROOT/linear120-trigger-candidate.txt"); fi
        for file in "${files[@]}"; do
            while read -r reg value; do
                i2ctransfer -f -y "$bus" "w3@$addr" "0x${reg:2:2}" "0x${reg:4:2}" "$value"
                if [[ $reg == 0x0103 ]]; then sleep 0.01; fi
            done < "$file"
        done
        for reg in 3018 3019 301f 3208 3209 320a 320b 320c 320d 320e 320f 3222 3225 300a 36e9 36f9 4837; do
            printf 'bus=%s addr=%s reg=%s value=' "$bus" "$addr" "$reg"
            i2ctransfer -f -y "$bus" "w2@$addr" "0x${reg:0:2}" "0x${reg:2:2}" r1
        done >> registers.txt
    done
    kill -0 "$capture_pid"
    if [[ $mode == trigger ]]; then kill -USR1 "$generator_pid"; fi
    i2ctransfer -f -y 18 w3@0x32 0x01 0x00 0x01
    i2ctransfer -f -y 16 w3@0x30 0x01 0x00 0x01
    set +e
    wait "$capture_pid"
    status=$?
    set -e
    capture_pid=
    echo "$status" > exit-status.txt
    if [[ -n $generator_pid ]]; then
        kill "$generator_pid"; wait "$generator_pid" || true; generator_pid=
    fi
    echo "mode=$mode requested_rate=$rate checker_exit=$status"
    cat capture.log
done
journalctl -k --since '-3 minutes' --no-pager > "$OUT/kernel.log"