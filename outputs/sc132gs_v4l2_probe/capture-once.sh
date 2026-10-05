#!/bin/sh
set -eu

OUT=${1:-/tmp/sc132gs.raw}
COUNT=${2:-3}

# Intentionally do not unload camera modules here. qcom_camss has an unsafe
# hot-unplug path on this Ubuntu kernel; this script is for a clean boot only.
modprobe sc132gs
modprobe qcom_camss
sleep 2

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -x "$SCRIPT_DIR/configure-sc132gs-pipeline" ]; then
	CONFIGURE="$SCRIPT_DIR/configure-sc132gs-pipeline"
else
	CONFIGURE="$SCRIPT_DIR/configure-sc132gs-pipeline.sh"
fi
sh "$CONFIGURE"

echo "=== controls ==="
SENSOR_DEV=$(media-ctl -d /dev/media1 -e 'sc132gs 16-0032' 2>/dev/null || true)
if [ -n "$SENSOR_DEV" ]; then
	v4l2-ctl -d "$SENSOR_DEV" --list-ctrls 2>/dev/null || true
fi
echo "=== IRQ before ==="
grep -E 'camss_msm_csiphy1|camss_msm_csid0|camss_msm_vfe0' /proc/interrupts

rm -f "$OUT"
DISCOVER=${DISCOVER:-/usr/local/sbin/sc132gs-discover}
CAM0=$("$DISCOVER" cam0)
timeout 10 v4l2-ctl -d "$CAM0" \
	--stream-mmap=4 \
	--stream-count="$COUNT" \
	--stream-to="$OUT" \
	--stream-poll || true

echo "=== capture ==="
stat -c '%n: %s bytes' "$OUT"
sha256sum "$OUT"
echo "=== IRQ after ==="
grep -E 'camss_msm_csiphy1|camss_msm_csid0|camss_msm_vfe0' /proc/interrupts
echo "=== sensor/CAMSS log ==="
dmesg | grep -E 'sc132gs|qcom-camss|duplicated lane|VFE reset' | tail -80
