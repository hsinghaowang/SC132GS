#!/usr/bin/env bash
# Preserve the current guarded driver, not the historical factory driver.
set -euo pipefail
ROOT=/home/ubuntu/sc132gs-kernel-sync-20261014
KERNEL=$(uname -r)
test "$KERNEL" = 6.8.0-1084-qcom
TARGET=/lib/modules/$KERNEL/updates/sc132gs-csid-monitor/qcom-camss.ko
OPTIONS=/etc/modprobe.d/sc132gs-csid-monitor.conf
CONTROL=/sys/bus/platform/devices/acb3000.camss/fsync_control
case ${1:?backup, record, common, restore} in
backup)
    test ! -e "$ROOT/backup"
    mkdir -m 700 "$ROOT/backup"
    cp -a "$TARGET" "$ROOT/backup/qcom-camss.ko"
    cp -a "$OPTIONS" "$ROOT/backup/options.conf"
    cp -a /boot/initrd.img-"$KERNEL" "$ROOT/backup/initrd.img"
    cp -a /var/lib/sc132gs-camera/settings.yaml "$ROOT/backup/settings.yaml"
    cp -a /home/ubuntu/stereo-h265-rtsp/run-stereo-rtsp.sh "$ROOT/backup/run-stereo-rtsp.sh"
    cp -a /home/ubuntu/stereo-h265-rtsp/build-main10/stereo-h265-rtsp "$ROOT/backup/stereo-h265-rtsp"
    systemctl cat sc132gs-camera-rtsp.service sc132gs-camera-restore.service > "$ROOT/backup/services.txt"
    dmesg --color=never > "$ROOT/backup/dmesg.txt"
    sha256sum "$ROOT/backup/"* > "$ROOT/backup.sha256"
    ;;
record|common)
    sha256sum -c "$ROOT/backup.sha256" > /dev/null
    mode=1
    extra=
    if [[ $1 == common ]]; then
        test -s "$ROOT/characterization-passed.json"
        python3 - "$ROOT/characterization-passed.json" "$2" "$3" <<'PY'
import json, sys
r=json.load(open(sys.argv[1]))
assert r['passed'] is True
assert r['trigger_hz']==30 and r['frame_step']==1
assert [int(sys.argv[2]), int(sys.argv[3])]==[r['sof_min_us'],r['sof_max_us']]
PY
        mode=2
        offset=${4:-0}
        if ((offset != 0)); then
            python3 "$ROOT/validate_timestamp_estimate.py" "$ROOT/timestamp-estimate.json" "$offset"
        fi
        extra="sof_min_us=${2:?minimum delay} sof_max_us=${3:?maximum delay} timestamp_offset_ns=$offset"
    fi
    # Stop observers through their normal signal handler so their rings survive.
    for pid in $(pgrep -f '^/usr/bin/python3 /home/ubuntu/camss-dma-fix-20261013/watch_camera_dma_ring.py' || true); do
        kill -TERM "$pid"
        for ((n=0;n<100;n++)); do
            if ! kill -0 "$pid" 2>/dev/null; then break; fi
            sleep 0.1
        done
        if kill -0 "$pid" 2>/dev/null; then echo 'Observer did not exit'; exit 1; fi
    done
    systemctl stop sc132gs-camera-restore.service sc132gs-camera-rtsp.service
    test -z "$(pgrep -x sc132gs-fsync-g || true)"
    install -m 644 "$ROOT/source/qcom-camss.ko" "$TARGET"
    printf 'options qcom_camss geometry_guard=1 fsync_mode=%s %s\n' "$mode" "$extra" > "$OPTIONS"
    install -m 755 "$ROOT/run-stereo-rtsp.sh" /home/ubuntu/stereo-h265-rtsp/run-stereo-rtsp.sh
    if [[ $mode == 2 ]]; then
        install -m 755 "$ROOT/userspace-build/stereo-h265-rtsp" /home/ubuntu/stereo-h265-rtsp/build-main10/stereo-h265-rtsp
    fi
    if [[ -e /etc/systemd/system/sc132gs-camera-restore.service.d/kernel-fsync.conf ]]; then
        grep -q 'sc132gs-kernel-sync-20261014/preflight.sh' /etc/systemd/system/sc132gs-camera-restore.service.d/kernel-fsync.conf
    fi
    mkdir -p /etc/systemd/system/sc132gs-camera-restore.service.d
    printf '[Service]\nExecStartPre=/bin/bash /home/ubuntu/sc132gs-kernel-sync-20261014/preflight.sh\n' > /etc/systemd/system/sc132gs-camera-restore.service.d/kernel-fsync.conf
    systemctl daemon-reload
    depmod -a "$KERNEL"
    update-initramfs -u -k "$KERNEL"
    sha256sum "$TARGET" /boot/initrd.img-"$KERNEL" > "$ROOT/deployed.sha256"
    ;;
restore)
    sha256sum -c "$ROOT/backup.sha256" > /dev/null
    systemctl stop sc132gs-camera-restore.service sc132gs-camera-rtsp.service
    if [[ -e $CONTROL ]]; then printf 'stop\n' > "$CONTROL"; fi
    cp -a "$ROOT/backup/qcom-camss.ko" "$TARGET"
    cp -a "$ROOT/backup/options.conf" "$OPTIONS"
    cp -a "$ROOT/backup/run-stereo-rtsp.sh" /home/ubuntu/stereo-h265-rtsp/run-stereo-rtsp.sh
    cp -a "$ROOT/backup/stereo-h265-rtsp" /home/ubuntu/stereo-h265-rtsp/build-main10/stereo-h265-rtsp
    cp -a "$ROOT/backup/settings.yaml" /var/lib/sc132gs-camera/settings.yaml
    rm -f /etc/systemd/system/sc132gs-camera-restore.service.d/kernel-fsync.conf
    systemctl daemon-reload
    depmod -a "$KERNEL"
    cp -a "$ROOT/backup/initrd.img" /boot/initrd.img-"$KERNEL"
    ;;
*) exit 2;;
esac
sync
echo 'Prepared; use a cold reboot to change the running module.'
