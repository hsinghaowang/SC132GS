#!/usr/bin/env python3
"""Bounded live regression: preserve evidence and fail on new DMA faults/stalls."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time

parser = argparse.ArgumentParser()
parser.add_argument('output', type=Path)
parser.add_argument('--seconds', type=int, default=3600)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=False)

def command(*argv):
    result = subprocess.run(argv, text=True, capture_output=True, timeout=10)
    return result.returncode, result.stdout, result.stderr

def kernel():
    # Default dmesg timestamps are seconds since boot. "raw" is not a
    # --time-format value on the board's util-linux build.
    code, output, error = command('dmesg', '--color=never')
    if code:
        raise RuntimeError(error)
    return output

baseline = kernel()
last_stamp = max(float(m.group(1)) for m in re.finditer(r'^\[\s*(\d+\.\d+)\]', baseline, re.M))
(args.output / 'dmesg-before.txt').write_text(baseline)
boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
started = time.monotonic()
previous_pairs = None
log_path = Path('/run/sc132gs-camera-server.log')
failure = None
with (args.output / 'samples.jsonl').open('w') as samples:
    while time.monotonic() - started < args.seconds:
        code, state, _ = command('systemctl', 'is-active', 'sc132gs-camera-rtsp.service')
        log = log_path.read_text()
        counters = re.findall(r'input_fps=([^ ]+).*?encoded_fps=([^ ]+).*?pairs=(\d+)', log)
        current = kernel()
        fresh = '\n'.join(line for line in current.splitlines()
                          if (match := re.match(r'^\[\s*(\d+\.\d+)\]', line))
                          and float(match.group(1)) > last_stamp)
        faults = bool(re.search(r'Unhandled context fault|SOFTWARE TABLE WALK FAILED|Internal error: Oops', fresh))
        pairs = int(counters[-1][2]) if counters else None
        sample = dict(elapsed_s=round(time.monotonic()-started, 2), boot_id=boot,
                      service=state.strip(), last_metrics=counters[-1] if counters else None,
                      new_kernel_fault=faults)
        samples.write(json.dumps(sample)+'\n')
        samples.flush()
        if code or faults:
            failure = 'new kernel fault' if faults else 'camera service stopped'
        if previous_pairs is not None and (pairs is None or pairs <= previous_pairs):
            failure = 'capture counter stopped progressing'
        if pairs is None and time.monotonic()-started > 30:
            failure = 'capture metrics missing'
        if Path('/proc/sys/kernel/random/boot_id').read_text().strip() != boot:
            failure = 'boot changed'
        if failure:
            break
        previous_pairs = pairs
        print(json.dumps(sample), flush=True)
        time.sleep(10)

(args.output / 'dmesg-after.txt').write_text(kernel())
(args.output / 'server-after.log').write_text(log_path.read_text())
code, status, error = command('sc132gs-camera', 'status')
(args.output / 'status-after.txt').write_text(status+error)
report = dict(passed=failure is None and code == 0, failure=failure,
              elapsed_s=time.monotonic()-started, boot_id=boot,
              scope='bounded capture progression and kernel faults; not indefinite stability')
(args.output / 'result.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report), flush=True)
raise SystemExit(0 if report['passed'] else 1)
