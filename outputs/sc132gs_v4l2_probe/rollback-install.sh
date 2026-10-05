#!/usr/bin/env bash
set -euo pipefail

sudo rm -f /etc/grub.d/41_sc132gs_v4l2
sudo rm -f /etc/modules-load.d/sc132gs.conf
sudo rm -f /lib/modules/6.8.0-1084-qcom/extra/sc132gs.ko
sudo rm -rf /boot/dtb/sc132gs
sudo depmod -a 6.8.0-1084-qcom
sudo update-grub
printf 'Removed the SC132GS V4L2 test boot entry and test artifacts.\n'
