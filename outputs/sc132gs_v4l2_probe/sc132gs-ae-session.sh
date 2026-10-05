#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
set -eu

CAPTURE_UNIT=sc132gs-ae-capture
FSYNC_UNIT=sc132gs-ae-fsync
SOCKET=/run/sc132gs-ae.sock

if [ "$(id -u)" -ne 0 ]; then
	echo "Run with sudo: sc132gs-ae-session start|stop|status" >&2
	exit 2
fi

stop_session() {
	systemctl stop "$CAPTURE_UNIT" 2>/dev/null || true
	systemctl stop "$FSYNC_UNIT" 2>/dev/null || true
	if ! systemctl is-active --quiet "$CAPTURE_UNIT"; then
		rm -f "$SOCKET"
	fi
}

if [ "$#" -ne 1 ]; then
	echo "usage: sc132gs-ae-session start|stop|status" >&2
	exit 2
fi

case "$1" in
start)
	if systemctl is-active --quiet "$CAPTURE_UNIT"; then
		sc132gs-ctl status
		exit 0
	fi
	stop_session
	modprobe qcom_camss
	/usr/local/sbin/configure-sc132gs-dual-pipeline >/dev/null
	/usr/local/sbin/prepare-sc132gs-sync-gpios
	systemctl reset-failed "$FSYNC_UNIT" "$CAPTURE_UNIT" 2>/dev/null || true
	systemd-run --unit="$FSYNC_UNIT" --collect \
		/usr/local/bin/sc132gs-fsync-generator auto 18 19 60 100 active-low
	sleep 0.2
	if ! systemctl is-active --quiet "$FSYNC_UNIT"; then
		echo "FSYNC generator failed to arm" >&2
		exit 1
	fi
	trap stop_session EXIT
	DISCOVER=${DISCOVER:-/usr/local/sbin/sc132gs-discover}
	CAM0=$("$DISCOVER" cam0)
	CAM1=$("$DISCOVER" cam1)
	systemd-run --unit="$CAPTURE_UNIT" --collect \
		-p StandardOutput=null -p StandardError=journal \
		/usr/local/bin/sc132gs-paired-stream "$CAM0" "$CAM1" 3 1000
	ready=0
	i=0
	while [ "$i" -lt 40 ]; do
		if [ -S "$SOCKET" ] &&
		   systemctl is-active --quiet "$CAPTURE_UNIT"; then
			ready=1
			break
		fi
		sleep 0.05
		i=$((i + 1))
	done
	if [ "$ready" -ne 1 ]; then
		echo "paired capture did not arm" >&2
		exit 1
	fi
	# A previous 30 FPS session may have left exposure above one 60 FPS
	# interval. Restore the known-good initial value before applying FSYNC.
	for sensor in /sys/class/video4linux/v4l-subdev*; do
		case "$(cat "$sensor/name")" in
		"sc132gs "*-0032|"sc132gs "*-0030)
			v4l2-ctl -d "/dev/$(basename "$sensor")" \
				--set-ctrl=exposure=808
			;;
		esac
	done
	systemctl kill -s USR1 "$FSYNC_UNIT"
	sleep 0.5
	printf 1 > /sys/bus/i2c/devices/18-0032/trigger_60fps
	printf 1 > /sys/bus/i2c/devices/16-0030/trigger_60fps
	trap - EXIT
	sleep 0.5
	sc132gs-ctl status
	;;
stop)
	stop_session
	;;
status)
	sc132gs-ctl status
	;;
*)
	echo "usage: sc132gs-ae-session start|stop|status" >&2
	exit 2
	;;
esac
