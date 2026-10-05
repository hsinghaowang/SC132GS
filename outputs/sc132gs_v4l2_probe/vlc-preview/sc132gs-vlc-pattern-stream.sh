#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Stream matched RAW10 pairs for the Windows VLC MJPEG bridge.
set -eu

FSYNC_UNIT=sc132gs-vlc-fsync
CAPTURE_LOG=/tmp/sc132gs-vlc-capture.log
capture_pid=

sensor_nodes() {
	for sensor in /sys/class/video4linux/v4l-subdev*; do
		case "$(cat "$sensor/name")" in
		"sc132gs "*-0032|"sc132gs "*-0030)
			echo "/dev/$(basename "$sensor")"
			;;
		esac
	done
}

cleanup() {
	if [ -n "$capture_pid" ]; then
		kill "$capture_pid" 2>/dev/null || true
		wait "$capture_pid" 2>/dev/null || true
	fi
	systemctl stop "$FSYNC_UNIT" 2>/dev/null || true
	for dev in $(sensor_nodes); do
		v4l2-ctl -d "$dev" --set-ctrl=test_pattern=0 2>/dev/null || true
	done
}
trap cleanup EXIT INT TERM

if systemctl is-active --quiet sc132gs-ae-capture; then
	echo 'The AE capture already owns the cameras.' >&2
	exit 1
fi

modprobe qcom_camss
/usr/local/sbin/configure-sc132gs-dual-pipeline >/dev/null
/usr/local/sbin/prepare-sc132gs-sync-gpios >&2
for dev in $(sensor_nodes); do
	v4l2-ctl -d "$dev" --set-ctrl=exposure=808,analogue_gain=62,test_pattern=1
done

systemctl reset-failed "$FSYNC_UNIT" 2>/dev/null || true
systemd-run --unit="$FSYNC_UNIT" --collect \
	/usr/local/bin/sc132gs-fsync-generator auto 18 19 60 100 active-low >&2
sleep 0.2
if ! systemctl is-active --quiet "$FSYNC_UNIT"; then
	echo 'FSYNC generator failed to arm.' >&2
	exit 1
fi

: > "$CAPTURE_LOG"
DISCOVER=${DISCOVER:-/usr/local/sbin/sc132gs-discover}
CAM0=$("$DISCOVER" cam0)
CAM1=$("$DISCOVER" cam1)
/usr/local/bin/sc132gs-paired-stream "$CAM0" "$CAM1" 6 1000 \
	2>"$CAPTURE_LOG" &
capture_pid=$!

armed=0
attempt=0
while [ "$attempt" -lt 100 ]; do
	if grep -q 'paired stream armed' "$CAPTURE_LOG"; then
		armed=1
		break
	fi
	if ! kill -0 "$capture_pid" 2>/dev/null; then
		break
	fi
	attempt=$((attempt + 1))
	sleep 0.05
done
if [ "$armed" -ne 1 ]; then
	cat "$CAPTURE_LOG" >&2
	echo 'The paired capture did not arm.' >&2
	exit 1
fi

printf 1 > /sys/bus/i2c/devices/18-0032/trigger_60fps
printf 1 > /sys/bus/i2c/devices/16-0030/trigger_60fps
systemctl kill -s USR1 "$FSYNC_UNIT"
echo 'Both test patterns are streaming at 60 Hz FSYNC.' >&2
wait "$capture_pid"
capture_pid=
