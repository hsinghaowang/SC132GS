#!/usr/bin/env python3
from pathlib import Path
import sys
source, destination = map(Path, sys.argv[1:])
text = source.read_text()
anchor = 'generator_pid=\n'
if text.count(anchor) != 1:
    raise SystemExit('Unexpected runner')
insertion = '''# Opt-in kernel ownership; mode 1 is diagnostics, mode 2 is exact capture.
KERNEL_FSYNC=/sys/bus/platform/devices/acb3000.camss/fsync_control
if [[ -e $KERNEL_FSYNC ]]; then
    [[ $mode_status == 'ok camera_mode=linear '* && $FPS == 30 ]] || {
        echo 'Kernel FSYNC currently supports Linear 30 FPS only.' >&2; exit 1;
    }
    printf 'stop\\n' > "$KERNEL_FSYNC"
    printf 'start\\n' > "$KERNEL_FSYNC"
    trap 'printf "stop\\n" > "$KERNEL_FSYNC"' EXIT
    trap 'exit 130' INT TERM
    CONSUMER_CPUS=$(python3 /home/ubuntu/sc132gs-kernel-sync-20261014/camera_cpu_list.py)
    taskset --cpu-list "$CONSUMER_CPUS" "$SERVER_BIN" --cam0 "$CAM0" --cam1 "$CAM1" \\
        --bind "$BIND" --port "$PORT" --mount /stereo \\
        --downscale "$DOWNSCALE" --fps "$FPS" --brightness "$BRIGHTNESS" \\
        --auto-exposure "$AE_MODE" --hevc-profile "$HEVC_PROFILE" --bitrate "$BITRATE"
    exit $?
fi

'''
destination.write_text(text.replace(anchor, insertion + anchor), newline='\n')
