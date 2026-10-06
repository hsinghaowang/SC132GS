#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PREPARE_GPIOS=${PREPARE_GPIOS:-/usr/local/sbin/prepare-sc132gs-sync-gpios}
FSYNC_BIN=${FSYNC_BIN:-/usr/local/bin/sc132gs-fsync-generator}
SERVER_BIN=${SERVER_BIN:-$SCRIPT_DIR/build/stereo-h265-rtsp}
DISCOVER=${DISCOVER:-/usr/local/sbin/sc132gs-discover}
CAM0=${CAM0:-$("$DISCOVER" cam0)}
CAM1=${CAM1:-$("$DISCOVER" cam1)}
BIND=${BIND:-127.0.0.1}
PORT=${PORT:-8554}
DOWNSCALE=${DOWNSCALE:-1}
FPS=${FPS:-30}
if [[ -r /sys/module/sc132gs/parameters/hdr ]] &&
   [[ $(cat /sys/module/sc132gs/parameters/hdr) == Y ]] && (( FPS != 30 )); then
    echo 'The installed SC132GS HDR mode requires FPS=30.' >&2
    exit 1
fi
BRIGHTNESS=${BRIGHTNESS:-40}
FSYNC_LOG=${FSYNC_LOG:-/tmp/sc132gs-rtsp-fsync.log}

generator_pid=
cleanup() {
    if [[ -n $generator_pid ]]; then
        kill "$generator_pid" 2>/dev/null || true
        wait "$generator_pid" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

"$PREPARE_GPIOS"
: > "$FSYNC_LOG"
"$FSYNC_BIN" auto 18 19 "$FPS" 100 active-low > "$FSYNC_LOG" 2>&1 &
generator_pid=$!

armed=0
for ((attempt=0; attempt<100; ++attempt)); do
    if grep -q 'FSYNC generator armed' "$FSYNC_LOG"; then
        armed=1
        break
    fi
    if ! kill -0 "$generator_pid" 2>/dev/null; then break; fi
    sleep 0.05
done
if ((armed == 0)); then
    cat "$FSYNC_LOG" >&2
    echo 'FSYNC generator did not arm' >&2
    exit 1
fi

# Matches the already verified bring-up order: start periodic FSYNC before
# both V4L2 receivers STREAMON. The service captures every trigger directly.
kill -USR1 "$generator_pid"
"$SERVER_BIN" --cam0 "$CAM0" --cam1 "$CAM1" \
    --bind "$BIND" --port "$PORT" --mount /stereo \
    --downscale "$DOWNSCALE" --fps "$FPS" --brightness "$BRIGHTNESS"
