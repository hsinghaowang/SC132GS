#!/usr/bin/env bash
# Only reprobe an unbound CAMSS. Never unbind a working capture device.
set -euo pipefail
MODE=/sys/module/qcom_camss/parameters/fsync_mode
if [[ ! -e $MODE ]]; then
    grep -q 'fsync_mode=[12]' /etc/modprobe.d/sc132gs-csid-monitor.conf || exit 0
    /usr/local/sbin/prepare-sc132gs-sync-gpios
    modprobe qcom_camss
fi
[[ $(cat "$MODE") != 0 ]] || exit 0
/usr/local/sbin/prepare-sc132gs-sync-gpios
DEVICE=/sys/bus/platform/devices/acb3000.camss
if [[ ! -e $DEVICE/fsync_control ]]; then
    [[ ! -e $DEVICE/driver ]] || { echo 'Unexpected bound CAMSS'; exit 1; }
    printf 'acb3000.camss\n' > /sys/bus/platform/drivers_probe
fi
test -e "$DEVICE/fsync_control"
