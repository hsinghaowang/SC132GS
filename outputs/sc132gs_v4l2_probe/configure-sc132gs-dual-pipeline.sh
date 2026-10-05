#!/bin/sh
set -eu

DISCOVER=${DISCOVER:-/usr/local/sbin/sc132gs-discover}
if [ -z "${MEDIA:-}" ]; then
	MEDIA=$("$DISCOVER" media)
fi
FMT=SRGGB10_1X10/1088x1280
TOPOLOGY=$(media-ctl -d "$MEDIA" -p)
CAM0=$(printf '%s\n' "$TOPOLOGY" | sed -n 's/^- entity [0-9][0-9]*: \(sc132gs [^ ]*-0032\) .*/\1/p' | head -n 1)
CAM1=$(printf '%s\n' "$TOPOLOGY" | sed -n 's/^- entity [0-9][0-9]*: \(sc132gs [^ ]*-0030\) .*/\1/p' | head -n 1)

if [ -z "$CAM0" ] || [ -z "$CAM1" ]; then
	echo "Expected both SC132GS entities (I2C 0x32 and 0x30)" >&2
	exit 1
fi

# Camera 0: SC132GS on CCI1/0x32 -> CSIPHY1 -> CSID0 -> VFE0 RDI0
media-ctl -d "$MEDIA" --links '"msm_csiphy1":1 -> "msm_csid0":0 [1]'
media-ctl -d "$MEDIA" --links '"msm_csid0":1 -> "msm_vfe0_rdi0":0 [1]'
media-ctl -d "$MEDIA" --set-v4l2 '"'"$CAM0"'":0 [fmt:'"$FMT"' field:none]'
media-ctl -d "$MEDIA" --set-v4l2 '"msm_csiphy1":0 [fmt:'"$FMT"' field:none]'
media-ctl -d "$MEDIA" --set-v4l2 '"msm_csiphy1":1 [fmt:'"$FMT"' field:none]'
media-ctl -d "$MEDIA" --set-v4l2 '"msm_csid0":0 [fmt:'"$FMT"' field:none]'
media-ctl -d "$MEDIA" --set-v4l2 '"msm_csid0":1 [fmt:'"$FMT"' field:none]'
media-ctl -d "$MEDIA" --set-v4l2 '"msm_vfe0_rdi0":0 [fmt:'"$FMT"' field:none]'
media-ctl -d "$MEDIA" --set-v4l2 '"msm_vfe0_rdi0":1 [fmt:'"$FMT"' field:none]'

# Camera 1: SC132GS on CCI0/0x30 -> CSIPHY4 -> CSID1 -> VFE1 RDI0
media-ctl -d "$MEDIA" --links '"msm_csiphy4":1 -> "msm_csid1":0 [1]'
media-ctl -d "$MEDIA" --links '"msm_csid1":1 -> "msm_vfe1_rdi0":0 [1]'
media-ctl -d "$MEDIA" --set-v4l2 '"'"$CAM1"'":0 [fmt:'"$FMT"' field:none]'
media-ctl -d "$MEDIA" --set-v4l2 '"msm_csiphy4":0 [fmt:'"$FMT"' field:none]'
media-ctl -d "$MEDIA" --set-v4l2 '"msm_csiphy4":1 [fmt:'"$FMT"' field:none]'
media-ctl -d "$MEDIA" --set-v4l2 '"msm_csid1":0 [fmt:'"$FMT"' field:none]'
media-ctl -d "$MEDIA" --set-v4l2 '"msm_csid1":1 [fmt:'"$FMT"' field:none]'
media-ctl -d "$MEDIA" --set-v4l2 '"msm_vfe1_rdi0":0 [fmt:'"$FMT"' field:none]'
media-ctl -d "$MEDIA" --set-v4l2 '"msm_vfe1_rdi0":1 [fmt:'"$FMT"' field:none]'
CAM0_NODE=$("$DISCOVER" cam0 --media "$MEDIA")
CAM1_NODE=$("$DISCOVER" cam1 --media "$MEDIA")
set_capture_format() {
	current=$(v4l2-ctl -d "$1" --get-fmt-video)
	if printf '%s\n' "$current" | grep -q 'Width/Height[[:space:]]*: 1088/1280' &&
	   printf '%s\n' "$current" | grep -q "Pixel Format[[:space:]]*: 'pRAA'"; then
		return
	fi
	v4l2-ctl -d "$1" --set-fmt-video=width=1088,height=1280,pixelformat=pRAA
}
set_capture_format "$CAM0_NODE"
set_capture_format "$CAM1_NODE"
printf 'CAM0=%s CAM1=%s\n' "$CAM0_NODE" "$CAM1_NODE"
