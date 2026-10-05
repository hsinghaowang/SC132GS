#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
FRAMES=${1:-600}
FPS=${2:-60}
DISCOVER=${DISCOVER:-/usr/local/sbin/sc132gs-discover}
CAM0=$("$DISCOVER" cam0)
CAM1=$("$DISCOVER" cam1)
FSYNC_LOG=${FSYNC_LOG:-/tmp/sc132gs-capture-check-fsync.log}

generator_pid=
cleanup() {
    if [[ -n $generator_pid ]]; then
        kill "$generator_pid" 2>/dev/null || true
        wait "$generator_pid" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

/usr/local/sbin/prepare-sc132gs-sync-gpios
: > "$FSYNC_LOG"
/usr/local/bin/sc132gs-fsync-generator auto 18 19 "$FPS" 100 active-low > "$FSYNC_LOG" 2>&1 &
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

kill -USR1 "$generator_pid"
"$SCRIPT_DIR/build/stereo-capture-check" "$FRAMES" "$FPS" "$CAM0" "$CAM1"
