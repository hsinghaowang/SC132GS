#!/usr/bin/env bash
set -euo pipefail

# Temporary diagnostic: compare shorter integration in external-trigger mode
# with a live switch to free-run, using the same 60 Hz FSYNC source.
# Sensor power-off during STREAMOFF restores the driver's mode table next run.

if (( EUID != 0 )); then
    echo 'Run as root so the test can access GPIO and sensor I2C.' >&2
    exit 2
fi

generator_pid=
check_pid=
cleanup() {
    if [[ -n $generator_pid ]]; then
        kill "$generator_pid" 2>/dev/null || true
        wait "$generator_pid" 2>/dev/null || true
    fi
    if [[ -n $check_pid ]]; then
        kill "$check_pid" 2>/dev/null || true
        wait "$check_pid" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

generator_log=/tmp/sc132gs-60-short-exposure-fsync.log
check_log=/tmp/sc132gs-60-short-exposure-check.log
frames=${FRAMES:-600}
test_timeout=${TEST_TIMEOUT:-35}
: > "$generator_log"
: > "$check_log"

/usr/local/sbin/prepare-sc132gs-sync-gpios
/usr/local/bin/sc132gs-fsync-generator auto 18 19 60 100 active-low \
    > "$generator_log" 2>&1 &
generator_pid=$!

armed=0
for ((attempt=0; attempt<100; ++attempt)); do
    if grep -q 'FSYNC generator armed' "$generator_log"; then
        armed=1
        break
    fi
    kill -0 "$generator_pid" 2>/dev/null || break
    sleep 0.05
done
if (( armed == 0 )); then
    cat "$generator_log"
    exit 1
fi

kill -USR1 "$generator_pid"
DISCOVER=${DISCOVER:-/usr/local/sbin/sc132gs-discover}
CAM0=$("$DISCOVER" cam0)
CAM1=$("$DISCOVER" cam1)
timeout "${test_timeout}s" /usr/local/bin/sc132gs-sync-check \
    "$CAM0" "$CAM1" "$frames" 500 8 \
    > "$check_log" 2>&1 &
check_pid=$!

armed=0
for ((attempt=0; attempt<100; ++attempt)); do
    if grep -q 'Both streams armed' "$check_log"; then
        armed=1
        break
    fi
    kill -0 "$check_pid" 2>/dev/null || break
    sleep 0.05
done
if (( armed == 0 )); then
    cat "$check_log"
    exit 1
fi

if [[ ${PROBE_MODE:-short_exposure} == short_exposure ]]; then
    # The public SC132GS table labels 0x3e01=0x32, 0x3e02=0x80 as 10 ms.
    # Scale its encoded value by ten for an approximately 1 ms diagnostic exposure.
    /usr/sbin/i2ctransfer -f -y 18 w3@0x32 0x3e 0x01 0x05
    /usr/sbin/i2ctransfer -f -y 18 w3@0x32 0x3e 0x02 0x00
    /usr/sbin/i2ctransfer -f -y 16 w3@0x30 0x3e 0x01 0x05
    /usr/sbin/i2ctransfer -f -y 16 w3@0x30 0x3e 0x02 0x00
    printf 'CAM0 exposure: '
    /usr/sbin/i2ctransfer -f -y 18 w2@0x32 0x3e 0x01 r2
    printf 'CAM1 exposure: '
    /usr/sbin/i2ctransfer -f -y 16 w2@0x30 0x3e 0x01 r2
elif [[ ${PROBE_MODE:-} == vts_normal ]]; then
    for target in '18 0x32' '16 0x30'; do
        read -r bus address <<< "$target"
        /usr/sbin/i2ctransfer -f -y "$bus" w3@"$address" 0x32 0x0e 0x05
        /usr/sbin/i2ctransfer -f -y "$bus" w3@"$address" 0x32 0x0f 0x78
    done
elif [[ ${PROBE_MODE:-} == trigger_gate_clear ]]; then
    for target in '18 0x32' '16 0x30'; do
        read -r bus address <<< "$target"
        /usr/sbin/i2ctransfer -f -y "$bus" w3@"$address" 0x32 0x25 0x00
    done
elif [[ ${PROBE_MODE:-} == mode_only ]]; then
    for target in '18 0x32' '16 0x30'; do
        read -r bus address <<< "$target"
        /usr/sbin/i2ctransfer -f -y "$bus" w3@"$address" 0x32 0x22 0x00
    done
elif [[ ${PROBE_MODE:-} == mode_and_vts ||
        ${PROBE_MODE:-} == mode_and_vts_no_fsync ]]; then
    for target in '18 0x32' '16 0x30'; do
        read -r bus address <<< "$target"
        /usr/sbin/i2ctransfer -f -y "$bus" w3@"$address" 0x32 0x0e 0x05
        /usr/sbin/i2ctransfer -f -y "$bus" w3@"$address" 0x32 0x0f 0x78
        /usr/sbin/i2ctransfer -f -y "$bus" w3@"$address" 0x32 0x22 0x00
    done
    if [[ $PROBE_MODE == mode_and_vts_no_fsync ]]; then
        kill "$generator_pid" 2>/dev/null || true
        wait "$generator_pid" 2>/dev/null || true
        generator_pid=
    fi
elif [[ ${PROBE_MODE:-} == free_run || ${PROBE_MODE:-} == free_run_no_fsync ]]; then
    # Diagnostic transition after stream-on. A fresh stream-on restores the
    # driver's external-trigger table; this is not a production mode switch.
    for target in '18 0x32' '16 0x30'; do
        read -r bus address <<< "$target"
        /usr/sbin/i2ctransfer -f -y "$bus" w3@"$address" 0x32 0x0e 0x05
        /usr/sbin/i2ctransfer -f -y "$bus" w3@"$address" 0x32 0x0f 0x78
        /usr/sbin/i2ctransfer -f -y "$bus" w3@"$address" 0x32 0x25 0x00
        /usr/sbin/i2ctransfer -f -y "$bus" w3@"$address" 0x32 0x22 0x00
    done
    printf 'CAM0 mode 0x3222: '
    /usr/sbin/i2ctransfer -f -y 18 w2@0x32 0x32 0x22 r1
    printf 'CAM1 mode 0x3222: '
    /usr/sbin/i2ctransfer -f -y 16 w2@0x30 0x32 0x22 r1
    if [[ $PROBE_MODE == free_run_no_fsync ]]; then
        kill "$generator_pid" 2>/dev/null || true
        wait "$generator_pid" 2>/dev/null || true
        generator_pid=
    fi
else
    echo "Unknown PROBE_MODE: $PROBE_MODE" >&2
    exit 2
fi

set +e
wait "$check_pid"
status=$?
set -e
check_pid=
kill "$generator_pid" 2>/dev/null || true
wait "$generator_pid" 2>/dev/null || true
generator_pid=
cat "$generator_log"
cat "$check_log"
exit "$status"
