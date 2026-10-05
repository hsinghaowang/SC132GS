#!/bin/sh
set -eu

cp /tmp/entry-original.dtb /tmp/entry-clock0.dtb
fdtput -t i /tmp/entry-clock0.dtb \
    /soc@0/cci@ac4a000/i2c-bus@0/camera@30/port/endpoint \
    clock-lanes 0
fdtput -t i /tmp/entry-clock0.dtb \
    /soc@0/camss@acaf000/ports/port@4/endpoint \
    clock-lanes 0

original_size=$(stat -c %s /tmp/entry-original.dtb)
patched_size=$(stat -c %s /tmp/entry-clock0.dtb)
test "$original_size" -eq "$patched_size"

offset=$(python3 -c "c=open('/tmp/combined-clock0.dtb','rb').read(); e=open('/tmp/entry-original.dtb','rb').read(); print(c.find(e))")
echo "entry_offset=$offset"
test "$offset" -ge 0

dd if=/tmp/entry-clock0.dtb of=/tmp/combined-clock0.dtb \
    bs=1 seek="$offset" conv=notrunc status=none

echo "sensor_clock=$(fdtget -t i /tmp/entry-clock0.dtb /soc@0/cci@ac4a000/i2c-bus@0/camera@30/port/endpoint clock-lanes)"
echo "camss_clock=$(fdtget -t i /tmp/entry-clock0.dtb /soc@0/camss@acaf000/ports/port@4/endpoint clock-lanes)"

sudo mkdir -p /mnt/dtb-build
sudo mount -o loop,rw /tmp/dtb-clock0.img /mnt/dtb-build
sudo cp /tmp/combined-clock0.dtb /mnt/dtb-build/combined-dtb.dtb
sync
sudo umount /mnt/dtb-build

sha256sum /tmp/dtb-clock0.img
stat -c '%n %s' /tmp/entry-clock0.dtb /tmp/combined-clock0.dtb /tmp/dtb-clock0.img
