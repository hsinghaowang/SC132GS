#!/bin/sh
set -eu

DISCOVER=${DISCOVER:-/usr/local/sbin/sc132gs-discover}
CAM0=$("$DISCOVER" cam0)
CAM1=$("$DISCOVER" cam1)

COUNT=${COUNT:-3}
TIMEOUT=${TIMEOUT:-15}
OUT_DIR=${OUT_DIR:-/tmp}

rm -f "$OUT_DIR/cam0.raw" "$OUT_DIR/cam1.raw" \
      "$OUT_DIR/cam0.log" "$OUT_DIR/cam1.log"

timeout "$TIMEOUT" v4l2-ctl -d "$CAM0" \
    --stream-mmap=4 --stream-count="$COUNT" \
    --stream-to="$OUT_DIR/cam0.raw" >"$OUT_DIR/cam0.log" 2>&1 &
pid0=$!

timeout "$TIMEOUT" v4l2-ctl -d "$CAM1" \
    --stream-mmap=4 --stream-count="$COUNT" \
    --stream-to="$OUT_DIR/cam1.raw" >"$OUT_DIR/cam1.log" 2>&1 &
pid1=$!

set +e
wait "$pid0"
status0=$?
wait "$pid1"
status1=$?
set -e

echo "CAM0 status=$status0"
cat "$OUT_DIR/cam0.log"
if [ -f "$OUT_DIR/cam0.raw" ]; then
    stat -c 'bytes=%s' "$OUT_DIR/cam0.raw"
else
    echo 'bytes=0'
fi

echo "CAM1 status=$status1"
cat "$OUT_DIR/cam1.log"
if [ -f "$OUT_DIR/cam1.raw" ]; then
    stat -c 'bytes=%s' "$OUT_DIR/cam1.raw"
else
    echo 'bytes=0'
fi

test "$status0" -eq 0 && test "$status1" -eq 0
