#!/usr/bin/env bash
# Bounded capture using a private trace instance; preserve the global tracer.
set -euo pipefail
OUT=${1:?evidence directory required}
SECONDS_TO_TRACE=${2:-20}
STALL=${3:-0}
STALL_TARGET=${4:-capture}
TRACE=/sys/kernel/debug/tracing/instances/sc132gs_dma
mkdir -p "$OUT"
test ! -e "$TRACE"
mkdir "$TRACE"
cleanup() {
    if [[ -n ${capture_pid:-} ]]; then kill -CONT "$capture_pid" 2>/dev/null || true; fi
    echo 0 > "$TRACE/tracing_on"
    cat "$TRACE/trace" > "$OUT/trace.txt"
    rmdir "$TRACE"
}
trap cleanup EXIT
dmesg > "$OUT/dmesg-before.txt"
cp /run/sc132gs-camera-server.log "$OUT/server-before.log"
systemctl cat sc132gs-camera-rtsp.service > "$OUT/service-before.txt"
echo 4096 > "$TRACE/buffer_size_kb"
echo 1 > "$TRACE/events/iommu/map/enable"
echo 1 > "$TRACE/events/iommu/unmap/enable"
echo 1 > "$TRACE/events/iommu/io_page_fault/enable"
for event in vb2_buf_queue vb2_buf_done vb2_qbuf vb2_dqbuf; do
    echo 'type == 9' > "$TRACE/events/vb2/$event/filter"
    echo 1 > "$TRACE/events/vb2/$event/enable"
done
echo 1 > "$TRACE/events/gpio/gpio_value/enable"
echo 1 > "$TRACE/tracing_on"
systemctl start sc132gs-camera-rtsp.service
if [[ $STALL != 0 ]]; then
    sleep 3
    if [[ $STALL_TARGET == fsync ]]; then
        capture_pid=$(pgrep -x sc132gs-fsync-g)
    else
        capture_pid=$(pgrep -x stereo-h265-rts)
    fi
    kill -STOP "$capture_pid"
    sleep "$STALL"
    kill -CONT "$capture_pid"
fi
sleep "$SECONDS_TO_TRACE"
dmesg > "$OUT/dmesg-after.txt"
cp /run/sc132gs-camera-server.log "$OUT/server-after.log"
systemctl show sc132gs-camera-rtsp.service > "$OUT/service-after.txt"
