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
CTL=${CTL:-/usr/local/bin/sc132gs-ctl}
mode_status=$("$CTL" mode)
if [[ $mode_status == 'ok camera_mode=hdr '* ]]; then
    FPS=${FPS:-30}
    if (( FPS != 30 )); then
        echo 'SC132GS HDR mode requires FPS=30.' >&2
        exit 1
    fi
elif [[ $mode_status == 'ok camera_mode=linear '* ]]; then
    FPS=${FPS:-60}
    if (( FPS != 30 && FPS != 60 )); then
        echo 'SC132GS Linear mode requires FPS=30 or FPS=60.' >&2
        exit 1
    fi
else
    echo 'Cannot determine a consistent mode for both cameras.' >&2
    exit 1
fi
BRIGHTNESS=${BRIGHTNESS:-40}
AUTO_EXPOSURE=${AUTO_EXPOSURE:-1}
HEVC_PROFILE=${HEVC_PROFILE:-main}
BITRATE=${BITRATE:-20000000}
case "$AUTO_EXPOSURE" in
    1) AE_MODE=on ;;
    0) AE_MODE=off ;;
    *) echo 'AUTO_EXPOSURE must be 0 or 1.' >&2; exit 1 ;;
esac
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
    --downscale "$DOWNSCALE" --fps "$FPS" --brightness "$BRIGHTNESS" \
    --auto-exposure "$AE_MODE" --hevc-profile "$HEVC_PROFILE" --bitrate "$BITRATE"
