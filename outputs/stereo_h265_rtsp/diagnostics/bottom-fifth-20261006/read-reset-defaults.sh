#!/usr/bin/env bash
set -euo pipefail
capture_pid=
cleanup() {
    if [[ -n $capture_pid ]]; then kill "$capture_pid" 2>/dev/null || true; wait "$capture_pid" 2>/dev/null || true; fi
    systemctl start sc132gs-hdr-rtsp 2>/dev/null ||
        systemd-run --unit=sc132gs-hdr-rtsp --property=Restart=on-failure \
        --setenv=BIND=192.168.137.226 --setenv=FPS=30 --setenv=BRIGHTNESS=40 \
        /bin/bash /home/ubuntu/stereo-h265-rtsp/run-stereo-rtsp.sh
}
trap cleanup EXIT
systemctl stop sc132gs-hdr-rtsp
node=$(/usr/local/sbin/sc132gs-discover cam0)
timeout 5 v4l2-ctl -d "$node" --stream-mmap=4 --stream-count=1000 --stream-poll >/tmp/reset-defaults-capture.log 2>&1 &
capture_pid=$!
ready=0
for ((attempt=0; attempt<100; ++attempt)); do
    value=$(i2ctransfer -f -y 18 w2@0x32 0x01 0x00 r1)
    if [[ $value == 0x01 ]]; then ready=1; break; fi
    sleep 0.01
done
(( ready == 1 ))
echo 'Current HDR slave registers'
i2ctransfer -f -y 18 w2@0x32 0x32 0x20 r8
i2ctransfer -f -y 18 w2@0x32 0x32 0x28 r8
i2ctransfer -f -y 18 w3@0x32 0x01 0x00 0x00
i2ctransfer -f -y 18 w3@0x32 0x01 0x03 0x01
sleep 0.03
echo 'Sensor reset defaults'
i2ctransfer -f -y 18 w2@0x32 0x32 0x20 r8
i2ctransfer -f -y 18 w2@0x32 0x32 0x28 r8
i2ctransfer -f -y 18 w2@0x32 0x30 0x00 r4
i2ctransfer -f -y 18 w2@0x32 0x30 0x08 r4
i2ctransfer -f -y 18 w2@0x32 0x32 0x14 r8
