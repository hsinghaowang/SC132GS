#!/usr/bin/env python3
"""Read-only, bounded ABI-v2 capture/encoder regression on the RUBIK Pi."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import signal
import subprocess
import time

CONTROL = Path('/sys/bus/platform/devices/acb3000.camss/fsync_control')
BOOT = Path('/proc/sys/kernel/random/boot_id')
MODULE = Path('/sys/module/qcom_camss/srcversion')
LOG = Path('/run/sc132gs-camera-server.log')
SERVICE = 'sc132gs-camera-rtsp.service'
METRICS = re.compile(r'input_fps=([^ ]+).*?encoded_fps=([^ ]+).*?pairs=(\d+)')
FAULT = re.compile(r'Unhandled context fault|SOFTWARE TABLE WALK FAILED|'
                   r'ATOS generated a fault|Internal error: Oops|BUG:')
STAMP = re.compile(r'^\[\s*(\d+\.\d+)\]')


def command(*argv):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise RuntimeError(f'{argv[0]}: {result.stderr.strip()}')
    return result.stdout


def fields(text):
    return dict(token.split('=', 1) for token in text.split())


def service_state():
    text = command('systemctl', 'show', SERVICE, '--no-pager',
                   '--property=ActiveState,MainPID,ExecMainStartTimestampMonotonic')
    return dict(line.split('=', 1) for line in text.splitlines())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--seconds', type=float, default=3600)
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error('--seconds must be positive')
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    stopping = False
    failure = None
    incomplete = False
    first_sample = last_sample = None
    last_progress_elapsed = None
    count = 0

    def stop(signum, frame):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        boot = BOOT.read_text().strip()
        module = MODULE.read_text().strip()
        initial = fields(CONTROL.read_text())
        service = service_state()
        before = command('dmesg', '--color=never')
        watermark = max((float(m.group(1)) for line in before.splitlines()
                         if (m := STAMP.match(line))), default=0)
        (args.output / 'dmesg-before.txt').write_text(before)
        initial_log = LOG.read_text()
        log_start = len(initial_log)
        binary = Path('/home/ubuntu/stereo-h265-rtsp/build-main10/stereo-h265-rtsp')
        provenance = {'boot_id': boot, 'module_srcversion': module,
                      'service': service, 'initial_control': initial,
                      'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest()}
        (args.output / 'provenance.json').write_text(json.dumps(provenance, indent=2)+'\n')
        (args.output / 'status-before.txt').write_text(command('sc132gs-camera', 'status'))
        if 'Kernel FSYNC trigger timestamps: exact pairing' not in initial_log:
            failure = {'code': 'exact_capture_not_confirmed'}
        with (args.output / 'samples.jsonl').open('w') as stream:
            while not failure:
                elapsed = time.monotonic() - started
                sync = fields(CONTROL.read_text())
                state = service_state()
                log = LOG.read_text()
                matches = METRICS.findall(log)
                metrics = matches[-1] if matches else None
                kernel = command('dmesg', '--color=never')
                fresh = [line for line in kernel.splitlines()
                         if (m := STAMP.match(line)) and float(m.group(1)) > watermark
                         and FAULT.search(line)]
                pairs = int(metrics[2]) if metrics else None
                sample = {'elapsed_s': time.monotonic()-started, 'control': sync,
                          'service': state, 'metrics': metrics, 'kernel_faults': fresh}
                stream.write(json.dumps(sample)+'\n')
                stream.flush()
                count += 1
                if BOOT.read_text().strip() != boot or MODULE.read_text().strip() != module:
                    failure = {'code': 'driver_identity_changed'}
                elif state['ActiveState'] != 'active' or int(state['MainPID']) == 0:
                    failure = {'code': 'camera_service_stopped'}
                elif state != service:
                    failure = {'code': 'camera_service_restarted'}
                elif any(sync.get(k) != v for k, v in {
                        'abi': '2', 'trigger_hz': '30', 'frame_step': '1',
                        'locked_mask': '3',
                        'mode': '2', 'running': '1', 'error': '0', 'skipped': '0',
                        'session': initial['session']}.items()):
                    failure = {'code': 'invalid_sync_state', 'control': sync}
                elif sync['cpu'] == sync.get('worker_cpu'):
                    failure = {'code': 'producer_worker_share_cpu'}
                elif sync.get('startup_dropped') != initial.get('startup_dropped'):
                    failure = {'code': 'new_startup_drop_after_lock'}
                elif fresh:
                    failure = {'code': 'new_kernel_fault', 'lines': fresh}
                elif len(log) < log_start:
                    failure = {'code': 'server_log_reset'}
                elif 'capture_health ' in log[log_start:]:
                    failure = {'code': 'new_capture_health_event'}
                elif last_sample and (pairs is None or pairs < last_sample['pairs']):
                    failure = {'code': 'capture_counter_stopped'}
                elif (last_sample and pairs == last_sample['pairs'] and
                      sample['elapsed_s']-last_progress_elapsed >= 10):
                    failure = {'code': 'capture_counter_stopped'}
                elif metrics is None and elapsed > 30:
                    failure = {'code': 'capture_metrics_missing'}
                elif metrics and elapsed >= 30 and any(
                        not math.isfinite(float(rate)) or not 29.7 <= float(rate) <= 30.3
                        for rate in metrics[:2]):
                    failure = {'code': 'capture_or_encoder_fps_out_of_range',
                               'metrics': metrics}
                if pairs is not None:
                    if last_sample is None or pairs > last_sample['pairs']:
                        last_progress_elapsed = sample['elapsed_s']
                    current = {'pairs': pairs, 'elapsed_s': sample['elapsed_s']}
                    first_sample = first_sample or current
                    last_sample = current
                if failure or sample['elapsed_s'] >= args.seconds or stopping:
                    break
                time.sleep(min(10, args.seconds-sample['elapsed_s']))
        if stopping and not failure:
            failure = {'code': 'monitor_interrupted'}
            incomplete = True
        if not failure and (last_sample is None or count < 2):
            failure = {'code': 'insufficient_capture_evidence'}
            incomplete = True
        average_fps = None
        if first_sample and last_sample and last_sample['elapsed_s'] > first_sample['elapsed_s']:
            average_fps = ((last_sample['pairs']-first_sample['pairs']) /
                           (last_sample['elapsed_s']-first_sample['elapsed_s']))
            if args.seconds >= 600 and not 29.7 <= average_fps <= 30.3 and not failure:
                failure = {'code': 'capture_average_fps_out_of_range', 'fps': average_fps}
        (args.output / 'dmesg-after.txt').write_text(command('dmesg', '--color=never'))
        (args.output / 'server-after.log').write_text(LOG.read_text())
        (args.output / 'status-after.txt').write_text(command('sc132gs-camera', 'status'))
    except Exception as error:
        if not failure:
            failure = {'code': 'monitor_read_error', 'detail': str(error)}
            incomplete = True
        average_fps = None
    elapsed = time.monotonic()-started
    report = {'passed': failure is None and elapsed >= args.seconds,
              'failure': failure, 'inconclusive': incomplete, 'elapsed_s': elapsed,
              'requested_seconds': args.seconds, 'samples': count,
              'capture_average_fps': average_fps,
              'scope': 'bounded ABI2/30Hz session, capture/encoder FPS, health and kernel faults; '
                       'decode and optical/electrical timing require separate evidence'}
    (args.output / 'result.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report), flush=True)
    return 0 if report['passed'] else (2 if incomplete else 1)


if __name__ == '__main__':
    raise SystemExit(main())
