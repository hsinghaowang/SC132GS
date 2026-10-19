#!/usr/bin/env python3
"""Observe cached VFE IRQ values for the exact deployed CAMSS build.

No MMIO reads or camera actions: probe arguments come from the ISR's CPU
registers, software device ID, and its already populated stack array. Refuse
other module builds, instruction layouts, and existing probe names.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import struct
import subprocess
import time

MODULE = Path('/lib/modules/6.8.0-1084-qcom/updates/sc132gs-csid-monitor/qcom-camss.ko')
MODULE_SHA = '27a726f96a74daace3b9a705e5264dc0d239063dac72405967f4881c3415e3e0'
TRACE_ROOT = Path('/sys/kernel/debug/tracing')
GROUP = 'sc132gs_vfe_observer'
SITES = {'irq_flags': (0x74, 'vfe=+8(%x19):u8 status0=%x23:x32 status1=%x22:x32'),
         'irq_bus': (0x134, 'vfe=+8(%x19):u8 status0=%x23:x32 '
                      'bus0=+24($stack):x32 bus1=+28($stack):x32 bus2=+32($stack):x32')}


def command(*argv):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=5)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return result.stdout


def probe_command(text):
    # tracefs parses each write as a command. Python's append-mode file object
    # seeks to EOF, which this pseudo-file rejects. No O_TRUNC: preserve every
    # other observer's events.
    fd = os.open(TRACE_ROOT / 'kprobe_events', os.O_WRONLY | os.O_CLOEXEC)
    try:
        data = (text + '\n').encode()
        if os.write(fd, data) != len(data):
            raise RuntimeError('Short trace probe command write')
    finally:
        os.close(fd)


def verified_addresses():
    blob = MODULE.read_bytes()
    if hashlib.sha256(blob).hexdigest() != MODULE_SHA:
        raise RuntimeError('Module hash differs from verified disassembly')
    # Offsets below belong only to the SHA-pinned ELF. Also verify the loaded
    # module's build-id, not just the file that may have replaced it on disk.
    note = blob[0x800c0:0x800e4]
    if Path('/sys/module/qcom_camss/notes/.note.gnu.build-id').read_bytes() != note:
        raise RuntimeError('Loaded module differs from the pinned ELF')
    if command('modinfo', '-F', 'srcversion', 'qcom_camss').strip() != '93BFD442CB057A0FAFA8C97':
        raise RuntimeError('Unexpected CAMSS srcversion')
    function = 0x238c0
    location = command('addr2line', '-f', '-e', str(MODULE), hex(function))
    if 'vfe_isr\n' not in location or 'camss-vfe-17x.c:' not in location:
        raise RuntimeError('Pinned function is not the VFE-17x ISR')
    expected = {0x58: 0xb9400297, 0x6c: 0xb9400296,
                0x74: 0xf9400a74, 0x130: 0xd5033e9f, 0x134: 0xf9400a74}
    for offset, instruction in expected.items():
        if struct.unpack_from('<I', blob, 0x40 + function + offset)[0] != instruction:
            raise RuntimeError(f'ISR instruction changed at {offset:#x}')
    base = int(Path('/sys/module/qcom_camss/sections/.text').read_text().strip(), 16)
    return {name: base + function + site[0] for name, site in SITES.items()}


def run(output, instance, seconds, attach):
    if os.geteuid() != 0:
        raise RuntimeError('Root is required for kernel trace events')
    if not re.fullmatch(r'[a-z0-9_]+', instance):
        raise RuntimeError('Invalid private instance name')
    addresses = verified_addresses()
    events = TRACE_ROOT / 'kprobe_events'
    if any(f'{GROUP}/{name} ' in events.read_text() for name in SITES):
        raise RuntimeError('Observer probe names are already in use')
    trace = TRACE_ROOT / 'instances' / instance
    if attach and not trace.is_dir():
        raise RuntimeError('Existing private trace instance is absent')
    output.mkdir(parents=True, exist_ok=False)
    if not attach:
        trace.mkdir()
    registered = []
    stopped = False
    started = time.monotonic()
    reason = 'duration_complete'
    error = None

    def stop(_signum, _frame):
        nonlocal stopped
        stopped = True

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, stop)
    try:
        (output / 'verified-build.json').write_text(json.dumps(dict(
            module_sha256=MODULE_SHA, instance=instance, attach=attach,
            function='camss-vfe-17x.c:vfe_isr', site_offsets={name: SITES[name][0] for name in SITES},
            scope='cached IRQ snapshots only; no extra hardware register access'), indent=2) + '\n')
        for name, address in addresses.items():
            probe_command(f'p:{GROUP}/{name} {address:#x} {SITES[name][1]}')
            registered.append(name)
            (trace / 'events' / GROUP / name / 'filter').write_text('vfe == 0 || vfe == 1')
            (trace / 'events' / GROUP / name / 'enable').write_text('1')
        if not attach:
            (trace / 'trace_clock').write_text('mono')
            (trace / 'buffer_size_kb').write_text('1024')
            (trace / 'tracing_on').write_text('1')
        print(json.dumps(dict(state='armed', instance=instance, attach=attach)), flush=True)
        while time.monotonic() - started < seconds and not stopped:
            if not trace.exists():
                reason = 'parent_instance_completed'
                break
            if attach:
                try:
                    if (trace / 'tracing_on').read_text().strip() == '0':
                        reason = 'parent_instance_frozen'
                        # The parent is formatting its saved trace now. Keep
                        # descriptions alive until it removes the instance.
                except FileNotFoundError:
                    reason = 'parent_instance_completed'
                    break
            time.sleep(0.1)
        if stopped:
            reason = 'observer_stopped'
    except Exception as exc:
        reason = 'observer_error'
        error = str(exc)
        raise
    finally:
        if not attach and trace.exists():
            (trace / 'tracing_on').write_text('0')
            (output / 'trace.txt').write_text((trace / 'trace').read_text())
        (output / 'probe-stats.txt').write_text('\n'.join(
            line for line in (TRACE_ROOT / 'kprobe_profile').read_text().splitlines()
            if GROUP in line or (line.split() and line.split()[0] in SITES)) + '\n')
        for name in reversed(registered):
            enable = trace / 'events' / GROUP / name / 'enable'
            if enable.exists():
                enable.write_text('0')
            probe_command(f'-:{GROUP}/{name}')
        if not attach:
            os.rmdir(trace)
        report = dict(reason=reason, error=error, elapsed_s=time.monotonic() - started)
        (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--instance', default='sc132gs_vfe_irq')
    parser.add_argument('--attach', action='store_true')
    parser.add_argument('--seconds', type=int, default=8)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 3600:
        parser.error('--seconds must be in 1..3600')
    run(args.output, args.instance, args.seconds, args.attach)
