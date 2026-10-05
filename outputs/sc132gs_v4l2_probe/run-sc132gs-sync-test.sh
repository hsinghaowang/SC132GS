#!/bin/sh
set -eu

DISCOVER=${DISCOVER:-/usr/local/sbin/sc132gs-discover}
CAM0=${CAM0:-$("$DISCOVER" cam0)}
CAM1=${CAM1:-$("$DISCOVER" cam1)}
FRAMES=${FRAMES:-120}
MAX_DELTA_US=${MAX_DELTA_US:-500}
WARMUP_FRAMES=${WARMUP_FRAMES:-8}
GPIOCHIP=${GPIOCHIP:-auto}
FSYNC0=${FSYNC0:-18}
FSYNC1=${FSYNC1:-19}
FPS=${FPS:-30}
PULSE_US=${PULSE_US:-100}
POLARITY=${POLARITY:-active-low}
CHECK_LOG=${CHECK_LOG:-/tmp/sc132gs-sync-check.log}
GEN_LOG=${GEN_LOG:-/tmp/sc132gs-fsync-generator.log}
PREPARE_GPIOS=${PREPARE_GPIOS:-/usr/local/sbin/prepare-sc132gs-sync-gpios}

check_pid=
generator_pid=

cleanup() {
	if [ -n "$generator_pid" ]; then
		kill "$generator_pid" 2>/dev/null || true
		wait "$generator_pid" 2>/dev/null || true
	fi
	if [ -n "$check_pid" ]; then
		kill "$check_pid" 2>/dev/null || true
		wait "$check_pid" 2>/dev/null || true
	fi
}
trap cleanup EXIT INT TERM

rm -f "$CHECK_LOG" "$GEN_LOG"
"$PREPARE_GPIOS"
sc132gs-fsync-generator "$GPIOCHIP" "$FSYNC0" "$FSYNC1" "$FPS" "$PULSE_US" \
	"$POLARITY" >"$GEN_LOG" 2>&1 &
generator_pid=$!

generator_armed=0
attempt=0
while [ "$attempt" -lt 100 ]; do
	if grep -q 'FSYNC generator armed' "$GEN_LOG" 2>/dev/null; then
		generator_armed=1
		break
	fi
	if ! kill -0 "$generator_pid" 2>/dev/null; then
		break
	fi
	attempt=$((attempt + 1))
	sleep 0.05
done

if [ "$generator_armed" -ne 1 ]; then
	cat "$GEN_LOG"
	echo 'FSYNC generator did not arm.' >&2
	exit 1
fi

# A hardware-reset SC132GS must see the periodic FSYNC waveform before its
# stream-on transition.  Startup frames are discarded by the checker.
kill -USR1 "$generator_pid"

sc132gs-sync-check "$CAM0" "$CAM1" "$FRAMES" "$MAX_DELTA_US" \
	"$WARMUP_FRAMES" \
	>"$CHECK_LOG" 2>&1 &
check_pid=$!

armed=0
attempt=0
while [ "$attempt" -lt 100 ]; do
	if grep -q 'Both streams armed' "$CHECK_LOG" 2>/dev/null; then
		armed=1
		break
	fi
	if ! kill -0 "$check_pid" 2>/dev/null; then
		break
	fi
	attempt=$((attempt + 1))
	sleep 0.05
done

if [ "$armed" -ne 1 ]; then
	cat "$GEN_LOG"
	cat "$CHECK_LOG"
	echo 'Capture paths did not arm; FSYNC was not started.' >&2
	exit 1
fi

set +e
wait "$check_pid"
status=$?
set -e
check_pid=

kill "$generator_pid" 2>/dev/null || true
wait "$generator_pid" 2>/dev/null || true
generator_pid=

cat "$GEN_LOG"
cat "$CHECK_LOG"
exit "$status"
