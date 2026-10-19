#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/ubuntu/sc132gs-linear120-20261007
OUT=$ROOT/kendryte-single
capture_pid=
cleanup() {
    if [[ -n $capture_pid ]]; then kill "$capture_pid" 2>/dev/null || true; wait "$capture_pid" 2>/dev/null || true; fi
    systemctl start sc132gs-hdr-rtsp 2>/dev/null ||
        systemd-run --unit=sc132gs-hdr-rtsp --property=Restart=on-failure \
        --setenv=BIND=192.168.137.226 --setenv=FPS=60 --setenv=BRIGHTNESS=40 --setenv=AUTO_EXPOSURE=1 \
        /bin/bash /home/ubuntu/stereo-h265-rtsp/run-stereo-rtsp.sh
}
trap cleanup EXIT INT TERM
mkdir -p "$OUT"
cd "$OUT"
sc132gs-ctl mode | tee before-mode.txt
grep -q 'camera_mode=linear' before-mode.txt
systemctl stop sc132gs-hdr-rtsp
cam0=$(sc132gs-discover cam0)
timeout 30 "$ROOT/single-rate-check" "$cam0" 600 > capture.log 2>&1 &
capture_pid=$!
for ((attempt=0; attempt<100; ++attempt)); do
    grep -q 'Stream armed' capture.log && break
    sleep 0.01
done
grep -q 'Stream armed' capture.log
for file in "$ROOT/kendryte-120-registers.txt" "$ROOT/gs130wi-geometry-short-exposure.txt"; do
    while read -r reg value; do
        i2ctransfer -f -y 18 w3@0x32 "0x${reg:2:2}" "0x${reg:4:2}" "$value"
        if [[ $reg == 0x0103 ]]; then sleep 0.01; fi
    done < "$file"
done
for reg in 3018 3019 301f 3208 3209 320a 320b 320c 320d 320e 320f 3220 3222 3225 3031 3e01 3e02 36ea 36eb 36ec 36ed 36e9 36fa 36fb 36fc 36fd 36f9 4837; do
    printf 'reg=%s value=' "$reg"
    i2ctransfer -f -y 18 w2@0x32 "0x${reg:0:2}" "0x${reg:2:2}" r1
done > registers-before-stream.txt
kill -0 "$capture_pid"
i2ctransfer -f -y 18 w3@0x32 0x01 0x00 0x01
set +e
wait "$capture_pid"
status=$?
set -e
capture_pid=
echo "$status" > exit-status.txt
cat capture.log
cat registers-before-stream.txt
journalctl -k --since '-1 minute' --no-pager > kernel.log