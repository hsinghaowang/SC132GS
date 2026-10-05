#!/bin/sh
set -eu

cp /tmp/entry-crossed.dtb /tmp/entry-cam2-only.dtb

# The known-good 0x32 sensor is physically connected to CAM2/CCI0/CSIPHY4.
# Remove the absent CAM1 sensor and its CAMSS graph port.  Merely setting
# status="disabled" is insufficient for the graph walk used by this kernel:
# it still discovers the endpoint and waits for a subdevice that cannot bind.
fdtput -r /tmp/entry-cam2-only.dtb \
    /soc@0/cci@ac4b000/i2c-bus@0/camera@32
fdtput -r /tmp/entry-cam2-only.dtb \
    /soc@0/camss@acaf000/ports/port@1

python3 /tmp/replace-concatenated-dtb.py \
    /tmp/combined-crossed.dtb 12 /tmp/entry-cam2-only.dtb \
    /tmp/combined-cam2-only.dtb

cp /tmp/dtb-crossed.img /tmp/dtb-cam2-only.img
sudo mkdir -p /mnt/dtb-build
sudo mount -o loop,rw /tmp/dtb-cam2-only.img /mnt/dtb-build
sudo cp /tmp/combined-cam2-only.dtb /mnt/dtb-build/combined-dtb.dtb
sync
sudo umount /mnt/dtb-build

if fdtget /tmp/entry-cam2-only.dtb /soc@0/cci@ac4b000/i2c-bus@0/camera@32 >/dev/null 2>&1; then
    echo "absent sensor node still exists" >&2
    exit 1
fi
if fdtget /tmp/entry-cam2-only.dtb /soc@0/camss@acaf000/ports/port@1 >/dev/null 2>&1; then
    echo "absent CAMSS port still exists" >&2
    exit 1
fi
echo 'absent_sensor=removed'
echo 'absent_port=removed'
sha256sum /tmp/dtb-cam2-only.img
stat -c '%n %s' /tmp/entry-cam2-only.dtb /tmp/combined-cam2-only.dtb /tmp/dtb-cam2-only.img
