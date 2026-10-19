#!/usr/bin/env bash
# Preserve/restore the accepted 30 Hz deployment immediately preceding ABI 4.
set -euo pipefail
ROOT=/home/ubuntu/sc132gs-kernel-sync-20261014
BASE=$ROOT/exposure-start-baseline-20261015
KERNEL=$(uname -r)
test "$KERNEL" = 6.8.0-1084-qcom
TARGET=/lib/modules/$KERNEL/updates/sc132gs-csid-monitor/qcom-camss.ko
OPTIONS=/etc/modprobe.d/sc132gs-csid-monitor.conf
case ${1:?save or restore} in
save)
    test ! -e "$BASE"
    test "$(cat /sys/module/qcom_camss/srcversion)" = 57412C1900C47CD02376039
    mkdir -m 700 "$BASE"
    cp -a "$TARGET" "$BASE/qcom-camss.ko"
    cp -a "$OPTIONS" "$BASE/options.conf"
    cp -a /boot/initrd.img-"$KERNEL" "$BASE/initrd.img"
    cp -a /var/lib/sc132gs-camera/settings.yaml "$BASE/settings.yaml"
    cp -a /home/ubuntu/stereo-h265-rtsp/run-stereo-rtsp.sh "$BASE/run-stereo-rtsp.sh"
    cp -a /home/ubuntu/stereo-h265-rtsp/build-main10/stereo-h265-rtsp "$BASE/stereo-h265-rtsp"
    cp -a /etc/systemd/system/sc132gs-camera-restore.service.d/kernel-fsync.conf "$BASE/kernel-fsync.conf"
    cat /sys/bus/platform/devices/acb3000.camss/fsync_control > "$BASE/control.txt"
    systemctl cat sc132gs-camera-rtsp.service sc132gs-camera-restore.service > "$BASE/services.txt"
    dmesg --color=never > "$BASE/dmesg.txt"
    cp -a /run/sc132gs-camera-server.log "$BASE/server.log"
    sha256sum "$BASE/"* > "$ROOT/exposure-start-baseline.sha256"
    sha256sum -c "$ROOT/exposure-start-baseline.sha256"
    ;;
restore)
    sha256sum -c "$ROOT/exposure-start-baseline.sha256" > /dev/null
    systemctl stop sc132gs-camera-restore.service sc132gs-camera-rtsp.service
    printf 'stop\n' > /sys/bus/platform/devices/acb3000.camss/fsync_control
    cp -a "$BASE/qcom-camss.ko" "$TARGET"
    cp -a "$BASE/options.conf" "$OPTIONS"
    cp -a "$BASE/settings.yaml" /var/lib/sc132gs-camera/settings.yaml
    cp -a "$BASE/run-stereo-rtsp.sh" /home/ubuntu/stereo-h265-rtsp/run-stereo-rtsp.sh
    cp -a "$BASE/stereo-h265-rtsp" /home/ubuntu/stereo-h265-rtsp/build-main10/stereo-h265-rtsp
    cp -a "$BASE/kernel-fsync.conf" /etc/systemd/system/sc132gs-camera-restore.service.d/kernel-fsync.conf
    systemctl daemon-reload
    depmod -a "$KERNEL"
    cp -a "$BASE/initrd.img" /boot/initrd.img-"$KERNEL"
    ;;
*) exit 2;;
esac
sync
echo 'Saved/restored on disk. Reboot to change the running module; never hot-unload CAMSS.'
