#!/bin/sh
set -eu

INPUT=${1:-/tmp/cam2-known-good.raw}
FRAME_BYTES=1740800
EXPECTED_BYTES=$((FRAME_BYTES * 3))
ACTUAL_BYTES=$(stat -c %s "$INPUT")

echo "bytes=$ACTUAL_BYTES"
test "$ACTUAL_BYTES" -eq "$EXPECTED_BYTES"

n=0
while [ "$n" -lt 3 ]; do
	HASH=$(dd if="$INPUT" bs="$FRAME_BYTES" skip="$n" count=1 status=none | sha256sum | cut -d' ' -f1)
	echo "frame$n=$HASH"
	n=$((n + 1))
done
