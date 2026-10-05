#!/bin/sh
set -eu

cp /tmp/entry-dual-normal.dtb /tmp/entry-cam2-original-sensor.dtb

# Keep the original 0x30 sensor on CAM2/CCI0/CSIPHY4. Remove CAM1 and its
# graph port so CAMSS does not wait for an intentionally disconnected sensor.
fdtput -r /tmp/entry-cam2-original-sensor.dtb \
    /soc@0/cci@ac4b000/i2c-bus@0/camera@32
fdtput -r /tmp/entry-cam2-original-sensor.dtb \
    /soc@0/camss@acaf000/ports/port@1

python3 /tmp/replace-concatenated-dtb.py \
    /tmp/combined-dual-normal.dtb 12 \
    /tmp/entry-cam2-original-sensor.dtb \
    /tmp/combined-cam2-original-sensor.dtb

cp /tmp/dtb-dual-normal.img /tmp/dtb-cam2-original-sensor.img
sudo mkdir -p /mnt/dtb-build
sudo mount -o loop,rw /tmp/dtb-cam2-original-sensor.img /mnt/dtb-build
sudo cp /tmp/combined-cam2-original-sensor.dtb /mnt/dtb-build/combined-dtb.dtb
sync
sudo umount /mnt/dtb-build

if fdtget /tmp/entry-cam2-original-sensor.dtb /soc@0/cci@ac4b000/i2c-bus@0/camera@32 >/dev/null 2>&1; then
    echo "CAM1 sensor node still exists" >&2
    exit 1
fi
if fdtget /tmp/entry-cam2-original-sensor.dtb /soc@0/camss@acaf000/ports/port@1 >/dev/null 2>&1; then
    echo "CAM1 graph port still exists" >&2
    exit 1
fi

echo "cam2_reg=$(fdtget -t x /tmp/entry-cam2-original-sensor.dtb /soc@0/cci@ac4a000/i2c-bus@0/camera@30 reg)"
sha256sum /tmp/dtb-cam2-original-sensor.img
stat -c '%n %s' /tmp/entry-cam2-original-sensor.dtb /tmp/combined-cam2-original-sensor.dtb /tmp/dtb-cam2-original-sensor.img
