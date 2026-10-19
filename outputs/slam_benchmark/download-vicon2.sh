#!/usr/bin/env bash
set -euo pipefail
dest=/home/ubuntu/ros2_humble_ws/slam_benchmark/datasets
cd "$dest"
curl -fL --connect-timeout 20 --retry 3 --speed-limit 10000 --speed-time 60 -C - https://huggingface.co/datasets/GlowBond/EuRoC_MAV_Dataset/resolve/29d08aeb1c8d9dc5c30497cc538d9cc61f872bb7/vicon_room2.zip -o vicon_room2.zip.part >download-vicon2.txt 2>&1
echo '6daf2cbc2de9a6bc4e02866c99ed01c29a5c7c164756f06c4f72656192977cfc  vicon_room2.zip.part' | sha256sum -c - | tee checksum-vicon2.txt
mv vicon_room2.zip.part vicon_room2.zip
python3 -c 'import zipfile; z=zipfile.ZipFile("vicon_room2.zip"); print("\n".join(z.namelist()[:30]))' >vicon2-members.txt
