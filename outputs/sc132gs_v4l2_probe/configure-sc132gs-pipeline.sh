#!/bin/sh
set -eu

MEDIA=${MEDIA:-/dev/media1}
TOPOLOGY=$(media-ctl -d "$MEDIA" -p)
CAMERA=$(printf '%s\n' "$TOPOLOGY" | sed -n 's/^- entity [0-9][0-9]*: \(sc132gs [^ ]*-0032\) .*/\1/p' | head -n 1)

if [ -z "$CAMERA" ]; then
	echo "SC132GS camera at I2C address 0x32 was not found" >&2
	exit 1
fi

media-ctl -d "$MEDIA" --links '"msm_csiphy1":1 -> "msm_csid0":0 [1]'
media-ctl -d "$MEDIA" --links '"msm_csid0":1 -> "msm_vfe0_rdi0":0 [1]'

media-ctl -d "$MEDIA" --set-v4l2 '"'"$CAMERA"'":0 [fmt:SRGGB10_1X10/1088x1280 field:none]'
media-ctl -d "$MEDIA" --set-v4l2 '"msm_csiphy1":0 [fmt:SRGGB10_1X10/1088x1280 field:none]'
media-ctl -d "$MEDIA" --set-v4l2 '"msm_csiphy1":1 [fmt:SRGGB10_1X10/1088x1280 field:none]'
media-ctl -d "$MEDIA" --set-v4l2 '"msm_csid0":0 [fmt:SRGGB10_1X10/1088x1280 field:none]'
media-ctl -d "$MEDIA" --set-v4l2 '"msm_csid0":1 [fmt:SRGGB10_1X10/1088x1280 field:none]'
media-ctl -d "$MEDIA" --set-v4l2 '"msm_vfe0_rdi0":0 [fmt:SRGGB10_1X10/1088x1280 field:none]'
media-ctl -d "$MEDIA" --set-v4l2 '"msm_vfe0_rdi0":1 [fmt:SRGGB10_1X10/1088x1280 field:none]'

DISCOVER=${DISCOVER:-/usr/local/sbin/sc132gs-discover}
CAM0_NODE=$("$DISCOVER" cam0 --media "$MEDIA")
v4l2-ctl -d "$CAM0_NODE" \
	--set-fmt-video=width=1088,height=1280,pixelformat=pRAA
