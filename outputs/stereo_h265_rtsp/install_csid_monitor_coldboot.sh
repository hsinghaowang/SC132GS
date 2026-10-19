#!/usr/bin/env bash
# Install bounded RAW10 driver for the next boot. Never hot-reload CAMSS.
set -euo pipefail
ACTION=${1:?install, update or restore required}
ROOT=/home/ubuntu/camss-dma-fix-20261013
KERNEL=$(uname -r)
test "$KERNEL" = 6.8.0-1084-qcom
TARGET=/lib/modules/$KERNEL/updates/sc132gs-csid-monitor/qcom-camss.ko
OPTIONS=/etc/modprobe.d/sc132gs-csid-monitor.conf
BACKUP=$ROOT/coldboot-backup
case "$ACTION" in
    install)
        test ! -e "$TARGET"
        test ! -e "$OPTIONS"
        mkdir -p "$BACKUP"
        cp -a /boot/initrd.img-"$KERNEL" "$BACKUP/initrd.img.original"
        sha256sum "$BACKUP/initrd.img.original" > "$BACKUP/initrd.sha256"
        cp -a /var/lib/sc132gs-camera/settings.yaml "$BACKUP/settings.yaml"
        install -D -m 644 "$ROOT/source/drivers/media/platform/qcom/camss/qcom-camss.ko" "$TARGET"
        printf '%s\n' 'options qcom_camss geometry_guard=1' > "$OPTIONS"
        depmod -a "$KERNEL"
        update-initramfs -u -k "$KERNEL"
        modinfo -n qcom_camss
        ;;
    update)
        test -f "$BACKUP/initrd.img.original"
        test -f "$TARGET"
        install -m 644 "$ROOT/source/drivers/media/platform/qcom/camss/qcom-camss.ko" "$TARGET"
        printf '%s\n' 'options qcom_camss geometry_guard=1' > "$OPTIONS"
        depmod -a "$KERNEL"
        update-initramfs -u -k "$KERNEL"
        modinfo -n qcom_camss
        ;;
    restore)
        test -f "$BACKUP/initrd.img.original"
        sha256sum -c "$BACKUP/initrd.sha256"
        rm -f -- "$TARGET" "$OPTIONS"
        depmod -a "$KERNEL"
        cp -a "$BACKUP/initrd.img.original" /boot/initrd.img-"$KERNEL"
        modinfo -n qcom_camss
        ;;
    *) echo 'Expected install, update, or restore' >&2; exit 2 ;;
esac
sync
echo 'Requires a reboot to change the running driver; no hot reload performed.'
