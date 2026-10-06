#!/usr/bin/env bash
set -euo pipefail
cd /home/ubuntu/sc132gs-hdr-20261006
target=$(readlink -f /dev/disk/by-partlabel/dtb_a)
[[ $(lsblk -dn -o PARTLABEL "$target") == dtb_a ]]
[[ $(blockdev --getsize64 "$target") == 67108864 ]]
[[ -f dtb_a-before.img && -f combined-dtb-hdr-2lane.dtb && -f sc132gs.ko ]]
[[ -f modprobe-before.conf ]] || cp /etc/modprobe.d/sc132gs-external-trigger.conf modprobe-before.conf
mount -o remount,rw dtb-mount
cp combined-dtb-hdr-2lane.dtb dtb-mount/combined-dtb.dtb
sync
cmp combined-dtb-hdr-2lane.dtb dtb-mount/combined-dtb.dtb
umount dtb-mount
install -m 644 sc132gs.ko /lib/modules/"$(uname -r)"/extra/sc132gs.ko
printf '%s\n' 'options sc132gs external_trigger=1 hdr=1' > /etc/modprobe.d/sc132gs-external-trigger.conf
depmod -a
sha256sum /lib/modules/"$(uname -r)"/extra/sc132gs.ko combined-dtb-hdr-2lane.dtb
echo 'Installed two-lane HDR configuration; reboot required.'
