#!/usr/bin/env bash
set -euo pipefail
cd /home/ubuntu/sc132gs-hdr-20261006
target=$(readlink -f /dev/disk/by-partlabel/dtb_a)
[[ $(lsblk -dn -o PARTLABEL "$target") == dtb_a ]]
[[ $(blockdev --getsize64 "$target") == 67108864 ]]
[[ -f combined-dtb-before.dtb && -f sc132gs-before.ko && -f modprobe-before.conf ]]
mountpoint -q dtb-mount || mount "$target" dtb-mount
mount -o remount,rw dtb-mount
cp combined-dtb-before.dtb dtb-mount/combined-dtb.dtb
sync
cmp combined-dtb-before.dtb dtb-mount/combined-dtb.dtb
umount dtb-mount
install -m 644 sc132gs-before.ko /lib/modules/"$(uname -r)"/extra/sc132gs.ko
install -m 644 modprobe-before.conf /etc/modprobe.d/sc132gs-external-trigger.conf
depmod -a
echo 'Restored previous driver and one-lane Device Tree; reboot required.'
