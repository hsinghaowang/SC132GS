#!/usr/bin/env python3
"""Bounded, read-only camera monitor plus a finite IMU capture; never restarts owners."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import signal
import subprocess
import time

ROOT = Path('/home/ubuntu/sc132gs-stability-20261015')
CONTROL = Path('/sys/bus/platform/devices/acb3000.camss/fsync_control')
LOG = Path('/run/sc132gs-camera-server.log')
SERVICE = 'sc132gs-camera-rtsp.service'
IMU_ROOT = Path('/home/ubuntu/capture-api-20261015')
METRICS = re.compile(r'input_fps=([^ ]+).*?encoded_fps=([^ ]+).*?pairs=(\d+)')
FAULT = re.compile(r'Unhandled context fault|SOFTWARE TABLE WALK FAILED|ATOS generated a fault|Internal error: Oops|BUG:')


def command(*args):
    return subprocess.check_output(args, text=True, timeout=15)


def fields(text):
    return dict(token.split('=', 1) for token in text.split())


def service():
    return dict(line.split('=', 1) for line in command('systemctl', 'show', SERVICE,
        '--property=ActiveState,MainPID,ExecMainStartTimestampMonotonic').splitlines())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot(output):
    with output.open('w') as stream:
        subprocess.run(['python3', str(IMU_ROOT / 'outputs/gs130wi_imu/snapshot_registers.py')], stdout=stream, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--seconds', type=int, default=7200)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    stopping = False
    failure = None
    imu = None
    last_serial = 0
    lost = 0
    samples = 0
    first_pairs = last_pairs = None
    last_progress = started
    initial_state = service()
    initial = fields(CONTROL.read_text())
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    module = Path('/sys/module/qcom_camss/srcversion').read_text().strip()
    deployed = json.loads((ROOT / 'deployed-manifest.json').read_text())
    paths = [str(p) for p in json.loads((ROOT / 'baseline-manifest.json').read_text())
             if not p.startswith('/boot/') and not p.endswith('qcom-camss.ko')]
    hashes = {name: sha(name) for name in paths}
    if module != deployed['module_srcversion']:
        raise RuntimeError('running module is not the tested deployment')
    if initial_state['ActiveState'] != 'active' or initial['locked_mask'] != '3':
        raise RuntimeError('camera owner is not ready')
    before = command('dmesg', '--color=never')
    (args.output / 'dmesg-before.txt').write_text(before)
    before_lines = set(before.splitlines())
    provenance = dict(boot_id=boot, module_srcversion=module, control=initial,
                      service=initial_state, hashes=hashes, requested_seconds=args.seconds)
    (args.output / 'provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    snapshot(args.output / 'imu-before.json')
    initial_log = LOG.read_text()
    log_start = len(initial_log)
    if 'Kernel FSYNC exact pairing:' not in initial_log:
        raise RuntimeError('exact camera capture path not confirmed')

    def stop(signum, frame):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        with (args.output / 'imu.csv').open('w') as csv_file, (args.output / 'imu-summary.json').open('w') as imu_summary, \
             (args.output / 'events.txt').open('w') as events, (args.output / 'samples.jsonl').open('w') as statuses:
            imu = subprocess.Popen([str(IMU_ROOT / 'build-imu/gs130wi-imu'), '--seconds', str(args.seconds),
                '--gpiochip', '/dev/gpiochip4', '--line', '24', '--fsync'], stdout=csv_file, stderr=imu_summary)
            (args.output / 'imu-pid.txt').write_text(str(imu.pid) + '\n')
            deadline = started + args.seconds + 5
            next_status = started
            while True:
                for line in Path('/sys/kernel/debug/sc132gs_sync/events').read_text().splitlines():
                    if line.startswith('#'):
                        continue
                    tokens = line.split()
                    serial = int(tokens[0])
                    if int(tokens[1]) != int(initial['session']) or serial <= last_serial:
                        continue
                    if last_serial and serial != last_serial + 1:
                        lost += serial - last_serial - 1
                    events.write(line + '\n')
                    last_serial = serial
                events.flush()
                now = time.monotonic()
                if now >= next_status:
                    state = service()
                    sync = fields(CONTROL.read_text())
                    log = LOG.read_text()
                    values = METRICS.findall(log)
                    pairs = int(values[-1][2]) if values else 0
                    sample = dict(elapsed_s=now-started, control=sync, service=state,
                                  pairs=pairs, imu_pid=imu.pid, imu_exit=imu.poll(), lost_events=lost)
                    statuses.write(json.dumps(sample) + '\n')
                    statuses.flush()
                    samples += 1
                    if first_pairs is None:
                        first_pairs = pairs
                    if last_pairs is None or pairs > last_pairs:
                        last_progress = now
                    last_pairs = pairs
                    if state != initial_state:
                        failure = 'camera owner stopped or restarted'
                    elif Path('/proc/sys/kernel/random/boot_id').read_text().strip() != boot or Path('/sys/module/qcom_camss/srcversion').read_text().strip() != module:
                        failure = 'boot/module identity changed'
                    elif any(sync.get(key) != value for key, value in {
                        'abi': '4', 'mode': '2', 'trigger_hz': '30', 'frame_step': '1',
                        'locked_mask': '3', 'running': '1', 'error': '0', 'skipped': '0',
                        'session': initial['session'], 'source': initial['source'],
                        'timestamp_offset_ns': initial['timestamp_offset_ns']}.items()):
                        failure = 'invalid synchronization state'
                    elif lost:
                        failure = 'kernel event collector lost records'
                    elif now - last_progress > 15:
                        failure = 'camera progress stopped'
                    elif len(log) < log_start or 'capture_health ' in log[log_start:]:
                        failure = 'capture health event or log reset'
                    elif imu.poll() is not None and (imu.returncode != 0 or now < started + args.seconds - 1):
                        failure = 'IMU capture failed or ended early'
                    new_kernel = [line for line in command('dmesg', '--color=never').splitlines()
                                  if line not in before_lines and FAULT.search(line)]
                    if new_kernel:
                        failure = 'new kernel memory/DMA fault'
                    progress = dict(state='failed' if failure else 'running', elapsed_s=now-started,
                                    requested_seconds=args.seconds, pairs=pairs,
                                    pulses=int(sync['pulses']), failure=failure,
                                    sample_count=samples, imu_pid=imu.pid)
                    (args.output / 'progress.json').write_text(json.dumps(progress, indent=2) + '\n')
                    next_status = now + 5
                if failure or stopping or now >= deadline:
                    break
                time.sleep(min(1, deadline-now))
            if stopping and not failure:
                failure = 'monitor interrupted'
            if imu.poll() is None:
                if failure:
                    imu.terminate()
                imu.wait(timeout=15)
            if imu.returncode and not failure:
                failure = 'IMU capture exit failure'
    finally:
        if imu is not None and imu.poll() is None:
            imu.terminate()
            imu.wait(timeout=15)
        snapshot(args.output / 'imu-after.json')
        (args.output / 'server-after.log').write_text(LOG.read_text())
        (args.output / 'control-final.txt').write_text(CONTROL.read_text())
        (args.output / 'dmesg-after.txt').write_text(command('dmesg', '--color=never'))
    if json.loads((args.output / 'imu-before.json').read_text()) != json.loads((args.output / 'imu-after.json').read_text()):
        failure = failure or 'IMU configuration restoration mismatch'
    for path, expected in hashes.items():
        if sha(path) != expected:
            failure = failure or 'persistent configuration/binary changed'
    imu_result = json.loads((args.output / 'imu-summary.json').read_text())
    if imu_result.get('status') != 'ok' or not imu_result.get('restored'):
        failure = failure or 'IMU did not complete and restore'
    elapsed = time.monotonic() - started
    report = dict(passed=not failure and elapsed >= args.seconds, failure=failure,
                  elapsed_s=elapsed, requested_seconds=args.seconds, samples=samples,
                  first_pairs=first_pairs, last_pairs=last_pairs, events_lost=lost,
                  imu=imu_result, scope='bounded original RTSP + IMU continuous run; independent event/CSV replay still required')
    (args.output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
