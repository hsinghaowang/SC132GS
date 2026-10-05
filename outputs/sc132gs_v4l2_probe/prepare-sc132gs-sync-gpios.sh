#!/bin/sh
set -eu

DRIVER=/sys/bus/platform/drivers/reg-fixed-voltage

release_disabled_regulator() {
	device=$1
	expected_name=$2
	device_path=$DRIVER/$device

	# Missing link means this regulator has already been released.
	[ -L "$device_path" ] || return 0

	regulator=
	for candidate in "$device_path"/regulator/regulator.*; do
		[ -d "$candidate" ] || continue
		regulator=$candidate
		break
	done
	[ -n "$regulator" ] || {
		echo "$device: regulator class device not found" >&2
		exit 1
	}

	name=$(cat "$regulator/name")
	state=$(cat "$regulator/state")
	users=$(cat "$regulator/num_users")
	if [ "$name" != "$expected_name" ] || [ "$state" != disabled ] ||
	   [ "$users" != 0 ]; then
		echo "$device: refusing to release name=$name state=$state users=$users" >&2
		exit 1
	fi

	printf '%s' "$device" >"$DRIVER/unbind"
}

release_disabled_regulator 0.gpio-regulator camera1_vio_ldo
release_disabled_regulator 100000000.gpio-regulator camera2_vio_ldo

echo 'GPIO18/19 released for the common SC132GS FSYNC source'
