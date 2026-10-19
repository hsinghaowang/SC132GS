#!/usr/bin/env python3
"""Complete the original hour after a reporting-window false alarm.

Keeps the original failed result. Uses full server statistics to cover the
sampling gap, and checks the same sticky driver/session/service identity.
Never opens a capture device or changes camera configuration.
"""
import argparse
import datetime
import json
from pathlib import Path
import re
import signal
import time
from monitor_sync30_regression import (
    BOOT, CONTROL, FAULT, LOG, MODULE, STAMP, command, fields,
    service_state, statistics_profile)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--finish-at', required=True)
    args = parser.parse_args()
    deadline = datetime.datetime.fromisoformat(args.finish_at).timestamp()
    provenance = json.loads((args.baseline/'provenance.json').read_text())
    original_samples = [json.loads(line) for line in
                        (args.baseline/'samples.jsonl').read_text().splitlines()]
    first_pair = int(original_samples[0]['metrics'][2])
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output/'baseline-provenance.json').write_text(json.dumps(provenance, indent=2)+'\n')
    before = (args.baseline/'dmesg-before.txt').read_text()
    watermark = max((float(m.group(1)) for line in before.splitlines()
                     if (m := STAMP.match(line))), default=0)
    started = time.monotonic()
    stopped = False
    failure = None
    profile = None
    count = 0

    def stop(signum, frame):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        with (args.output/'samples.jsonl').open('w') as stream:
            while not stopped:
                sync = fields(CONTROL.read_text())
                service = service_state()
                log = LOG.read_text()
                profile = statistics_profile(log, first_pair)
                kernel = command('dmesg', '--color=never')
                faults = [line for line in kernel.splitlines() if (m := STAMP.match(line))
                          and float(m.group(1)) > watermark and FAULT.search(line)]
                sample = {'observed_at': datetime.datetime.now().astimezone().isoformat(),
                          'elapsed_s': time.monotonic()-started, 'control': sync,
                          'service': service, 'statistics': profile, 'kernel_faults': faults}
                stream.write(json.dumps(sample)+'\n'); stream.flush(); count += 1
                expected = {'abi': '2', 'trigger_hz': '30', 'frame_step': '1',
                            'mode': '2', 'running': '1', 'locked_mask': '3', 'error': '0',
                            'skipped': '0', 'session': provenance['initial_control']['session'],
                            'startup_dropped': provenance['initial_control']['startup_dropped']}
                if BOOT.read_text().strip() != provenance['boot_id'] or MODULE.read_text().strip() != provenance['module_srcversion']:
                    failure = {'code': 'driver_identity_changed'}
                elif service != provenance['service']:
                    failure = {'code': 'service_identity_changed'}
                elif any(sync.get(k) != value for k, value in expected.items()):
                    failure = {'code': 'invalid_sync_state', 'control': sync}
                elif faults:
                    failure = {'code': 'new_kernel_fault', 'lines': faults}
                elif not all(29.7 <= profile[key] <= 30.3 for key in
                             ('capture_average_fps', 'encoder_average_fps')):
                    failure = {'code': 'average_fps_out_of_range', 'statistics': profile}
                else:
                    first = re.search(r'pairs='+str(first_pair)+r'\b', log)
                    tail = log[first.start():]
                    if 'capture_health ' in tail:
                        failure = {'code': 'capture_health_event'}
                    elif any(float(v) != 0 for v in re.findall(r'dropped_fps=([^ ]+)', tail)):
                        failure = {'code': 'encoder_submission_dropped'}
                if failure or (time.time() >= deadline and profile['duration_s'] >= 3600):
                    break
                time.sleep(10)
        if stopped and not failure:
            failure = {'code': 'monitor_interrupted'}
        (args.output/'dmesg-after.txt').write_text(command('dmesg', '--color=never'))
        (args.output/'server-after.log').write_text(LOG.read_text())
        (args.output/'status-after.txt').write_text(command('sc132gs-camera', 'status'))
    except Exception as error:
        failure = failure or {'code': 'verification_read_error', 'detail': str(error)}
    result = {'passed': failure is None and profile is not None and profile['duration_s'] >= 3600,
              'failure': failure, 'statistics': profile, 'new_samples': count,
              'new_observer_seconds': time.monotonic()-started,
              'baseline': str(args.baseline),
              'original_sampler_ended_after_s': original_samples[-1]['elapsed_s'],
              'scope': 'full original-hour server logs plus two sampler intervals; '
                       'sampling gap explicitly retained; sticky driver errors/session and '
                       'unchanged process identity checked; no camera restart'}
    (args.output/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result), flush=True)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
