#!/bin/sh
set -eu

BACKUP=/var/backups/sc132gs-v4l2-20260930-dtb-a/dtb_a.img
EXPECTED=ddd98b0497d708a26b2ed5b35e1423302159b908ef9d61029f6715d42032945f

actual=$(sha256sum "$BACKUP" | awk '{print $1}')
if [ "$actual" != "$EXPECTED" ]; then
	echo "Refusing restore: backup SHA-256 mismatch" >&2
	exit 1
fi

dd if="$BACKUP" of=/dev/sde2 bs=4M conv=fsync status=progress
sync
restored=$(sha256sum /dev/sde2 | awk '{print $1}')
if [ "$restored" != "$EXPECTED" ]; then
	echo "Restore write verification failed" >&2
	exit 1
fi

rm -f /etc/modprobe.d/blacklist-camera-qcm6490.conf
echo "Original dtb_a restored and vendor camera blacklist removed."
