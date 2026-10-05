#!/usr/bin/env bash
set -euo pipefail

printf 'Kernel: '
uname -r
printf 'Device-tree model: '
tr '\0' '\n' </sys/firmware/devicetree/base/model

printf '\nLoaded camera modules:\n'
lsmod | grep -E 'sc132gs|qcom_camss|i2c_qcom_cci|camera_qcm6490' || true

printf '\nCamera-related boot log:\n'
journalctl -b -k --no-pager \
  | grep -Ei 'sc132gs|camss|cci|csiphy|csid|vfe|media' \
  | tail -n 240 || true

printf '\nV4L2 devices:\n'
v4l2-ctl --list-devices || true

printf '\nMedia graphs:\n'
for media in /dev/media*; do
  printf '===== %s =====\n' "$media"
  media-ctl -d "$media" -p || true
done
