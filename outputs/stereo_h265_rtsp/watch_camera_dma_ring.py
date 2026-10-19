#!/usr/bin/env python3
"""Freeze a private trace ring at the first new capture-health event.

Observe an existing camera owner without restarting it, opening video devices,
reading MMIO, or changing the global tracer. A bounded run also saves its ring
when no fault occurs. This records evidence; it does not repair the camera.
"""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time


def command(*argv):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=5)
    if result.returncode:
        raise RuntimeError(f'{argv[0]} failed: {result.stderr.strip()}')
    return result.stdout


def run(output, seconds):
    if os.geteuid() != 0:
        raise RuntimeError('Run as root to access the private trace instance')
    command('systemctl', 'is-active', '--quiet', 'sc132gs-camera-rtsp.service')
    pids = command('pgrep', '-x', 'stereo-h265-rts').split()
    if len(pids) != 1:
        raise RuntimeError(f'Expected one existing capture owner, found {pids}')
    pid = int(pids[0])
    process = Path(f'/proc/{pid}')
    cmdline = (process / 'cmdline').read_bytes().replace(b'\0', b' ').decode()
    cam_nodes = re.findall(r'--cam[01] (/dev/video\d+)', cmdline)
    if len(cam_nodes) != 2 or cam_nodes[0] == cam_nodes[1]:
        raise RuntimeError(f'Cannot identify both cameras: {cmdline}')
    minors = [os.minor(os.stat(node).st_rdev) for node in cam_nodes]
    interrupts = Path('/proc/interrupts').read_text()
    irq_ids = [int(match.group(1)) for match in re.finditer(
        r'^\s*(\d+):.*camss_msm_(?:vfe|csid)[01]\s*$', interrupts, re.M)]
    if len(irq_ids) != 4:
        raise RuntimeError('Expected VFE0/1 and CSID0/1 IRQs')
    output.mkdir(parents=True, exist_ok=False)
    trace = Path('/sys/kernel/debug/tracing/instances/sc132gs_dma_ring')
    trace.mkdir()  # Refuse to take over an existing observer.
    reason = 'duration_complete'
    error = None
    created = time.monotonic()
    interrupted = False
    event_lines = []
    handlers = {}

    def stop(signum, _frame):
        nonlocal interrupted
        interrupted = True

    def write(relative, value):
        (trace / relative).write_text(str(value))

    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            handlers[signum] = signal.signal(signum, stop)
        (output / 'owner.json').write_text(json.dumps(dict(
            pid=pid, cmdline=cmdline, camera_minors=minors, irqs=irq_ids,
            boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            seconds_requested=seconds), indent=2) + '\n')
        (output / 'interrupts-before.txt').write_text(interrupts)
        (output / 'dmesg-before.txt').write_text(command('dmesg', '--color=never'))
        log_path = Path('/run/sc132gs-camera-server.log')
        log_identity = log_path.stat().st_ino
        (output / 'server-before.log').write_bytes(log_path.read_bytes())
        write('tracing_on', 0)
        write('current_tracer', 'nop')
        write('buffer_size_kb', 4096)  # Per CPU; bounded memory, no trace_pipe dump.
        write('trace_clock', 'mono')
        camera_filter = ' || '.join(f'minor == {minor}' for minor in minors)
        for event in ('v4l2_qbuf', 'v4l2_dqbuf'):
            write(f'events/v4l2/{event}/filter', camera_filter)
            write(f'events/v4l2/{event}/enable', 1)
        # This kernel does not emit vb2_v4l2_buf_done on the live capture path.
        # Generic VB2 events include the queue owner and hardware buffer index;
        # correlate their timestamps with the V4L2 dequeue minor above.
        for event in ('vb2_buf_queue', 'vb2_buf_done', 'vb2_qbuf', 'vb2_dqbuf'):
            write(f'events/vb2/{event}/filter', 'type == 9')
            write(f'events/vb2/{event}/enable', 1)
        irq_filter = ' || '.join(f'irq == {irq}' for irq in irq_ids)
        for event in ('irq_handler_entry', 'irq_handler_exit'):
            write(f'events/irq/{event}/filter', irq_filter)
            write(f'events/irq/{event}/enable', 1)
        write('events/gpio/gpio_value/filter', 'get == 0')
        write('events/gpio/gpio_value/enable', 1)
        write('events/iommu/io_page_fault/enable', 1)
        with log_path.open() as log:
            log.seek(0, os.SEEK_END)  # Historical health lines are not a trigger.
            write('tracing_on', 1)
            print(json.dumps(dict(state='armed', pid=pid, output=str(output))), flush=True)
            while time.monotonic() - created < seconds and not interrupted:
                if not process.exists():
                    reason = 'capture_owner_exited'
                    break
                stat = log_path.stat()
                if stat.st_ino != log_identity or stat.st_size < log.tell():
                    reason = 'capture_log_replaced'
                    break
                fresh = log.read()
                event_lines = [line for line in fresh.splitlines()
                               if line.startswith('capture_health ') or
                               'Unhandled context fault' in line or
                               line.startswith('stereo-h265-rtsp:')]
                if event_lines:
                    reason = 'capture_health_event'
                    break
                time.sleep(0.025)
        if interrupted:
            reason = 'observer_stopped'
    except Exception as exc:
        reason = 'observer_error'
        error = str(exc)
    finally:
        # Freeze before reading evidence; no camera/service actions in cleanup.
        write('tracing_on', 0)
        try:
            (output / 'trigger.json').write_text(json.dumps(dict(
                reason=reason, events=event_lines, error=error), indent=2) + '\n')
            (output / 'interrupts-after.txt').write_text(Path('/proc/interrupts').read_text())
            (output / 'trace.txt').write_text((trace / 'trace').read_text())
            (output / 'server-after.log').write_bytes(Path('/run/sc132gs-camera-server.log').read_bytes())
            (output / 'dmesg-after.txt').write_text(command('dmesg', '--color=never'))
            stats = {path.parent.name: path.read_text()
                     for path in (trace / 'per_cpu').glob('cpu*/stats')}
            report = dict(reason=reason, error=error,
                          elapsed_s=time.monotonic() - created, trace_stats=stats,
                          scope='bounded pre-fault event history; no camera repair')
            (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
            print(json.dumps(report), flush=True)
        finally:
            os.rmdir(trace)
            for signum, handler in handlers.items():
                signal.signal(signum, handler)
    if error:
        raise RuntimeError(error)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--seconds', type=int, default=3600)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 3600:
        parser.error('--seconds must be in 1..3600')
    run(args.output, args.seconds)
