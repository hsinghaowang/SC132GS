#!/usr/bin/env bash
# Board-specific experimental free-run test; restores the previous RTSP owner.
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROFILE_DIR=${PROFILE_DIR:-$SCRIPT_DIR/../sc132gs_v4l2_probe/linear120-evidence-20261007/profile-audit}
SERVER_BIN=${SERVER_BIN:-$SCRIPT_DIR/build-linear120/stereo-h265-rtsp}
BASELINE_UNIT=${BASELINE_UNIT:-sc132gs-hdr-rtsp}
BIND=${BIND:-192.168.137.226}
PORT=${PORT:-8554}
DOWNSCALE=${DOWNSCALE:-2}
DURATION_SECONDS=${DURATION_SECONDS:-60}
OUT=${OUT:-/tmp/sc132gs-rtsp120-$(date +%Y%m%d-%H%M%S)}
[[ $EUID == 0 ]] || { echo 'Run with sudo: camera and I2C access are required.' >&2; exit 1; }
[[ $DURATION_SECONDS =~ ^[0-9]+$ ]] || exit 1
[[ $DOWNSCALE == 1 || $DOWNSCALE == 2 || $DOWNSCALE == 4 ]] || exit 1
[[ -x $SERVER_BIN ]] || { echo "Missing experimental binary: $SERVER_BIN" >&2; exit 1; }
for file in kendryte-120-registers.txt gs130wi-geometry-short-exposure.txt; do
    [[ -r $PROFILE_DIR/$file ]] || { echo "Missing profile: $file" >&2; exit 1; }
done
mkdir -p "$OUT"
sc132gs-ctl mode | tee "$OUT/before-mode.txt"
grep -q 'camera_mode=linear' "$OUT/before-mode.txt" || {
    echo 'Switch both eyes to Linear before this experimental test.' >&2; exit 1;
}
systemctl cat "$BASELINE_UNIT" > "$OUT/before-unit.txt"
systemctl is-active --quiet "$BASELINE_UNIT" || {
    echo 'The baseline RTSP owner must be active for automatic restoration.' >&2; exit 1;
}
# Parse systemctl data as argument values; never execute it as shell code.
environment=$(systemctl show "$BASELINE_UNIT" -p Environment --value)
mapfile -t restore_env < <(python3 -c 'import shlex,sys; print("\n".join("--setenv="+s for s in shlex.split(sys.argv[1])))' "$environment")
cam0=$(sc132gs-discover cam0)
cam1=$(sc132gs-discover cam1)
for client in 18-0032 16-0030; do
    [[ $(cat "/sys/bus/i2c/devices/$client/name") == sc132gs ]] || {
        echo "Unexpected sensor identity at $client" >&2; exit 1;
    }
done
server_pid=
baseline_stopped=0
cleanup() {
    if [[ -n $server_pid ]]; then
        kill "$server_pid" 2>/dev/null || true
        wait "$server_pid" 2>/dev/null || true
    fi
    if ((baseline_stopped)); then
        systemctl start "$BASELINE_UNIT" 2>/dev/null ||
            systemd-run --unit="$BASELINE_UNIT" --property=Restart=on-failure \
            "${restore_env[@]}" /bin/bash "$SCRIPT_DIR/run-stereo-rtsp.sh"
    fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM
systemctl stop "$BASELINE_UNIT"
baseline_stopped=1
"$SERVER_BIN" --cam0 "$cam0" --cam1 "$cam1" --bind "$BIND" --port "$PORT" \
    --mount /stereo --downscale "$DOWNSCALE" --fps 120 --auto-exposure off \
    --capture-mode experimental-linear120-free-running > "$OUT/server.log" 2>&1 &
server_pid=$!
armed=0
for ((attempt=0; attempt<200; ++attempt)); do
    if grep -q 'Both 120 FPS receivers armed' "$OUT/server.log"; then armed=1; break; fi
    kill -0 "$server_pid" 2>/dev/null || break
    sleep 0.025
done
((armed)) || { cat "$OUT/server.log" >&2; exit 1; }
for device in '18 0x32' '16 0x30'; do
    read -r bus addr <<< "$device"
    for file in kendryte-120-registers.txt gs130wi-geometry-short-exposure.txt; do
        while read -r reg value; do
            value=${value%$'\r'}
            [[ $reg =~ ^0x[0-9a-fA-F]{4}$ && $value =~ ^0x[0-9a-fA-F]{2}$ ]] || exit 1
            i2ctransfer -f -y "$bus" "w3@$addr" "0x${reg:2:2}" "0x${reg:4:2}" "$value"
            if [[ $reg == 0x0103 ]]; then sleep 0.01; fi
        done < "$PROFILE_DIR/$file"
    done
    for reg in 3018 3019 3208 3209 320a 320b 320e 320f 3222 3225 36f9 4837; do
        printf 'bus=%s reg=%s value=' "$bus" "$reg"
        i2ctransfer -f -y "$bus" "w2@$addr" "0x${reg:0:2}" "0x${reg:2:2}" r1
    done >> "$OUT/registers.txt"
done
kill -0 "$server_pid"
i2ctransfer -f -y 18 w3@0x32 0x01 0x00 0x01
i2ctransfer -f -y 16 w3@0x30 0x01 0x00 0x01
echo "Experimental free-run RTSP: rtsp://$BIND:$PORT/stereo; logs=$OUT"
echo 'The 120/1 caps are a request; measure encoded/RTP/decoded FPS separately.'
deadline=$((SECONDS + DURATION_SECONDS))
while kill -0 "$server_pid" 2>/dev/null; do
    if ((DURATION_SECONDS > 0 && SECONDS >= deadline)); then break; fi
    sleep 1
done
if ! kill -0 "$server_pid" 2>/dev/null; then
    status=0
    wait "$server_pid" || status=$?
    server_pid=
    cat "$OUT/server.log"
    exit "$status"
else
    kill "$server_pid"
    wait "$server_pid" || true
    server_pid=
fi
cat "$OUT/server.log"
