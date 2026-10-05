#!/bin/sh
set -eu

MEDIA=${MEDIA:-/dev/media1}
FMT=SRGGB10_1X10/1088x1280
TOPOLOGY=$(media-ctl -d "$MEDIA" -p)
CAMERA=$(printf '%s\n' "$TOPOLOGY" | sed -n 's/^- entity [0-9][0-9]*: \(sc132gs [^ ]*\) (.*/\1/p' | head -n 1)

if [ -z "$CAMERA" ]; then
	echo "Expected one SC132GS entity on the CAM2-only graph" >&2
	exit 1
fi

# Single sensor on physical CAM2:
# CCI0 -> CSIPHY4 -> CSID1 -> VFE1 RDI0 -> discovered video node
media-ctl -d "$MEDIA" --links '"msm_csiphy4":1 -> "msm_csid1":0 [1]'
media-ctl -d "$MEDIA" --links '"msm_csid1":1 -> "msm_vfe1_rdi0":0 [1]'
media-ctl -d "$MEDIA" --set-v4l2 '"'"$CAMERA"'":0 [fmt:'"$FMT"' field:none]'
media-ctl -d "$MEDIA" --set-v4l2 '"msm_csiphy4":0 [fmt:'"$FMT"' field:none]'
media-ctl -d "$MEDIA" --set-v4l2 '"msm_csiphy4":1 [fmt:'"$FMT"' field:none]'
media-ctl -d "$MEDIA" --set-v4l2 '"msm_csid1":0 [fmt:'"$FMT"' field:none]'
media-ctl -d "$MEDIA" --set-v4l2 '"msm_csid1":1 [fmt:'"$FMT"' field:none]'
media-ctl -d "$MEDIA" --set-v4l2 '"msm_vfe1_rdi0":0 [fmt:'"$FMT"' field:none]'
media-ctl -d "$MEDIA" --set-v4l2 '"msm_vfe1_rdi0":1 [fmt:'"$FMT"' field:none]'
DISCOVER=${DISCOVER:-/usr/local/sbin/sc132gs-discover}
CAM1_NODE=$("$DISCOVER" cam1 --media "$MEDIA")
v4l2-ctl -d "$CAM1_NODE" --set-fmt-video=width=1088,height=1280,pixelformat=pRAA
