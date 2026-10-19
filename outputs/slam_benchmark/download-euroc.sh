#!/usr/bin/env bash
set -euo pipefail
dest=/home/ubuntu/ros2_humble_ws/slam_benchmark/datasets
mkdir -p "$dest"
cd "$dest"
url=https://huggingface.co/datasets/kavehsgh/EuRoC_MAV_Dataset_Machine_Hall_Easy_01/resolve/19434bff2188ded1943d3a01d5b5e6672afb117e/MH_01_easy.bag
curl -fL --connect-timeout 20 --retry 3 --speed-limit 10000 --speed-time 60 -C - "$url" -o MH_01_easy.bag.part >download.txt 2>&1
echo '57f440ccd68ec8dc8f9461269f5909656b86198bac3adfd677b1fcc7a1428fa9  MH_01_easy.bag.part' | sha256sum -c - | tee checksum.txt
mv MH_01_easy.bag.part MH_01_easy.bag
