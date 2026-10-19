#!/usr/bin/env python3
"""Independent bounded-memory replay of a stability_monitor run, without hardware access."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

PERIOD = 33_333_333
JITTER = 500_000
MIN_PERIOD = PERIOD - JITTER
PULSE = 100_000
OVERRUN = 25_000
SOF_MIN, SOF_MAX = 341_000, 16_853_000
READOUT_BOUND, GUARD = 15_500_000, 250_000


class Checks:
    def __init__(self):
        self.errors = Counter()
        self.examples = []

    def require(self, condition, name, detail=None):
        if not condition:
            self.errors[name] += 1
            if len(self.examples) < 30:
                self.examples.append(dict(check=name, detail=detail))


class Range:
    def __init__(self):
        self.count = 0
        self.minimum = self.maximum = None

    def add(self, value):
        self.count += 1
        self.minimum = value if self.minimum is None else min(self.minimum, value)
        self.maximum = value if self.maximum is None else max(self.maximum, value)

    def report(self):
        return dict(count=self.count, minimum=self.minimum, maximum=self.maximum)


def trace(path, session, checks):
    pulses, waiting = {}, {}
    sofs = [{}, {}]
    maps, hardware = {}, {}
    last = [None, None]
    first = [None, None]
    first_hw = [None, None]
    counts = [0, 0]
    kinds = Counter()
    ranges = {name: Range() for name in ('low_gpio_ns', 'high_release_overrun_ns',
        'pulse_outer_ns', 'low_spacing_ns', 'high_spacing_ns', 'sof_delay_ns',
        'readout_ns', 'frame_budget_ns', 'dma_after_sof_ns')}
    last_low = last_high = first_low = first_high = None
    serial = first_serial = None
    epoch_low = epoch_high = None
    leading = Counter()

    def with_pulse(event):
        _, _, kind, eye, ns, trigger, b, c, sequence, error = event
        pulse = pulses.get(trigger)
        if pulse is None:
            if first_low is not None and trigger < first_low[5]:
                leading['before_first_pulse'] += 1
            else:
                waiting.setdefault(trigger, []).append(event)
                checks.require(sum(map(len, waiting.values())) <= 1024, 'bounded_trigger_join')
            return
        delay = (ns if kind == 2 else c) - pulse[4]
        checks.require(SOF_MIN <= delay <= SOF_MAX, 'sof_in_characterized_window', event[0])
        if kind == 2:
            ranges['sof_delay_ns'].add(delay)
        else:
            readout = (hardware[(eye, sequence)][7] - b) * 10000 // 192
            budget = delay + readout + GUARD
            ranges['frame_budget_ns'].add(budget)
            checks.require(budget < MIN_PERIOD, 'frame_finishes_before_next_earliest_pulse', event[0])

    with path.open() as stream:
        for line_number, line in enumerate(stream, 1):
            if line.startswith('#') or not line.strip():
                continue
            try:
                e = tuple(map(int, line.split()))
                if len(e) != 10:
                    raise ValueError('expected ten event fields')
            except ValueError as error:
                checks.require(False, 'trace_parse', dict(line=line_number, error=str(error)))
                continue
            number, event_session, kind, eye, ns, a, b, c, seq, error = e
            checks.require(event_session == session, 'same_trace_session', number)
            checks.require(serial is None or number == serial + 1, 'trace_serial_contiguous', number)
            first_serial = number if first_serial is None else first_serial
            serial = number
            kinds[kind] += 1
            checks.require(not error or (error == 13 and kind in (2, 3)), 'trace_error', e)
            checks.require(kind not in (4, 10), 'fault_or_skipped_pulse', e)
            if kind == 1:
                if first_low is None:
                    first_low = e
                    for leading_id in [key for key in waiting if key < a]:
                        leading['before_first_pulse'] += len(waiting.pop(leading_id))
                checks.require(b >= ns and b - ns <= OVERRUN, 'low_gpio_duration', number)
                checks.require(c == 0, 'no_skipped_slots', number)
                ranges['low_gpio_ns'].add(b - ns)
                residual = ns - (a - 1) * PERIOD
                epoch_low = residual - JITTER if epoch_low is None else max(epoch_low, residual - JITTER)
                epoch_high = residual if epoch_high is None else min(epoch_high, residual)
                if last_low:
                    checks.require(a == last_low[5] + 1, 'pulse_id_contiguous', number)
                    spacing = ns - last_low[6]
                    ranges['low_spacing_ns'].add(spacing)
                    checks.require(spacing >= MIN_PERIOD, 'minimum_low_spacing', number)
                pulses[a] = e
                # The driver itself retains 128 pulses; this larger replay join
                # is bounded and tolerates asynchronous diagnostic publication.
                if len(pulses) > 1024:
                    del pulses[next(iter(pulses))]
                last_low = e
                for pending in waiting.pop(a, []):
                    with_pulse(pending)
            elif kind == 9:
                pulse = pulses.get(a)
                if pulse is None:
                    leading['high_before_first_low'] += 1
                    checks.require(first_low is None or a < first_low[5], 'high_has_low', number)
                    continue
                checks.require(c == pulse[6] + PULSE, 'pulse_end_reference', number)
                checks.require(ns >= c and ns <= b <= c + OVERRUN, 'protected_release_duration', number)
                ranges['high_release_overrun_ns'].add(b - c)
                ranges['pulse_outer_ns'].add(b - pulse[4])
                if last_high:
                    checks.require(a == last_high[5] + 1, 'high_id_contiguous', number)
                    spacing = ns - last_high[6]
                    ranges['high_spacing_ns'].add(spacing)
                    checks.require(spacing >= MIN_PERIOD, 'minimum_high_spacing', number)
                first_high = e if first_high is None else first_high
                last_high = e
            elif kind == 8:
                checks.require(eye in (0, 1), 'mapping_eye', number)
                maps[eye] = e
            elif kind == 2 and eye in (0, 1):
                mapping = maps.pop(eye, None)
                if mapping is not None:
                    checks.require(mapping[7] == 19_200_000 and mapping[6] >= b,
                                   'hardware_clock_domain', number)
                    expected = mapping[4] - (mapping[6] - b) * 10000 // 192
                    checks.require(expected == ns and mapping[5] == ns and mapping[8] + 1 == seq,
                                   'hardware_clock_mapping', number)
                else:
                    leading['sof_without_mapping'] += 1
                    checks.require(first_hw[eye] is None, 'sof_has_clock_mapping', number)
                first_hw[eye] = b if first_hw[eye] is None else first_hw[eye]
                checks.require(b not in sofs[eye], 'unique_hardware_sof', number)
                sofs[eye][b] = e
                checks.require(len(sofs[eye]) <= 64, 'bounded_sof_join', number)
                if a:
                    with_pulse(e)
            elif kind == 7:
                hardware[(eye, seq)] = e
            elif kind == 3 and eye in (0, 1):
                if not a:
                    if b:
                        sofs[eye].pop(b, None)
                    hardware.pop((eye, seq), None)
                    continue
                sof = sofs[eye].pop(b, None)
                if sof is None:
                    leading['dma_before_first_sof'] += 1
                    checks.require(first_hw[eye] is None or b < first_hw[eye], 'dma_has_sof', number)
                else:
                    checks.require((sof[4], sof[5], sof[6]) == (c, a, b), 'dma_matches_sof', number)
                hw = hardware.get((eye, seq))
                checks.require(hw is not None, 'dma_has_hardware_latches', number)
                if hw:
                    current, previous, eof = hw[5:8]
                    expected = current if eof >= current else previous
                    checks.require(0 < b <= eof and b == expected and
                                   (eof >= current or previous < current), 'dma_hardware_identity', number)
                    readout = (eof - b) * 10000 // 192
                    ranges['readout_ns'].add(readout)
                    checks.require(0 < readout <= READOUT_BOUND, 'characterized_readout_bound', number)
                    with_pulse(e)
                    # Keep only a small tail for late trigger-record joins.
                    while len(hardware) > 1024:
                        del hardware[next(iter(hardware))]
                if last[eye]:
                    prev = last[eye]
                    checks.require(a == prev[5] + 1 and seq == (prev[8] + 1) % 2**32,
                                   'per_eye_frame_contiguous', number)
                    checks.require(ns > prev[4] and c > prev[7] and b > prev[6],
                                   'per_eye_frame_monotonic', number)
                first[eye] = e if first[eye] is None else first[eye]
                last[eye] = e
                counts[eye] += 1
                ranges['dma_after_sof_ns'].add(ns - c)
    checks.require(first_low is not None and last_low is not None and all(first) and all(last), 'trace_not_empty')
    checks.require(last_low is not None and last_high is not None and
                   last_low[5] - last_high[5] in (0, 1), 'only_incomplete_tail_pulse')
    checks.require(not waiting, 'all_trigger_records_joined', list(waiting)[:10])
    checks.require(epoch_low is not None and epoch_low <= epoch_high, 'fixed_epoch_bounded_jitter')
    checks.require(all(len(pending) <= 1 for pending in sofs), 'only_incomplete_tail_sofs')
    checks.require(sum(leading.values()) <= 8, 'bounded_prefix_exceptions', dict(leading))
    eyes = {}
    for eye in (0, 1):
        if first[eye] and last[eye]:
            duration = (last[eye][7] - first[eye][7]) / 1e9
            fps = (counts[eye] - 1) / duration if duration else 0
            checks.require(29.7 <= fps <= 30.3, 'whole_trace_frame_rate', eye)
            eyes[str(eye)] = dict(frames=counts[eye], first_trigger=first[eye][5],
                last_trigger=last[eye][5], duration_s=duration, fps=fps)
    overlap = max(0, min(e[5] for e in last) - max(e[5] for e in first) + 1) if all(first) and all(last) else 0
    return dict(events=sum(kinds.values()), kinds=dict(kinds), first_serial=first_serial,
        last_serial=serial, eyes=eyes, common_trigger_interval_frames=overlap,
        leading_boundary_records=dict(leading), ranges={name: value.report() for name, value in ranges.items()},
        possible_epoch_interval_ns=[epoch_low, epoch_high])


def monitor(root, minimum, checks):
    provenance = json.loads((root / 'provenance.json').read_text())
    result = json.loads((root / 'result.json').read_text())
    checks.require(result['passed'] and result['elapsed_s'] >= minimum and result['events_lost'] == 0,
                   'completed_monitor_duration', result.get('failure'))
    first = last = None
    samples = 0
    with (root / 'samples.jsonl').open() as stream:
        for line in stream:
            sample = json.loads(line)
            samples += 1
            control = sample['control']
            checks.require(sample['service'] == provenance['service'], 'same_camera_process', samples)
            checks.require(sample['lost_events'] == 0 and sample['imu_pid'] > 0 and sample['imu_exit'] in (None, 0),
                           'monitor_collector_and_imu', samples)
            for key in ('abi', 'timestamp_offset_ns', 'source', 'session', 'mode', 'trigger_hz', 'frame_step'):
                checks.require(control[key] == provenance['control'][key], 'same_sync_' + key, samples)
            checks.require(all(control[key] == value for key, value in
                dict(error='0', error_count='0', skipped='0', running='1', locked_mask='3').items()),
                'healthy_sample', samples)
            if last:
                checks.require(0 < sample['elapsed_s'] - last['elapsed_s'] <= 10, 'continuous_monitor_sampling', samples)
                checks.require(sample['pairs'] > last['pairs'] and int(control['pulses']) > int(last['control']['pulses']),
                               'camera_progress_every_sample', samples)
            first = sample if first is None else first
            last = sample
    duration = last['elapsed_s'] - first['elapsed_s'] if last else 0
    # Samples are periodic: the final snapshot need not land exactly on the
    # duration boundary. The completed monitor and full trace must cover the
    # requested duration, with at most one bounded sampling interval at ends.
    checks.require(first is not None and first['elapsed_s'] <= 10 and
                   result['elapsed_s'] - last['elapsed_s'] <= 10 and duration >= minimum - 10,
                   'continuous_sample_coverage', duration)
    final_control = dict(token.split('=', 1) for token in (root / 'control-final.txt').read_text().split())
    checks.require(all(final_control[key] == provenance['control'][key] for key in
                   ('abi', 'timestamp_offset_ns', 'source', 'session', 'mode', 'trigger_hz', 'frame_step')) and
                   all(final_control[key] == value for key, value in
                   dict(error='0', error_count='0', skipped='0', running='1', locked_mask='3').items()),
                   'healthy_final_control')
    log = (root / 'server-after.log').read_text()
    metrics = re.compile(r'input_fps=([\d.]+) submitted_fps=([\d.]+) dropped_fps=([\d.]+) encoded_fps=([\d.]+).*?pairs=(\d+)')
    previous = None
    windows = 0
    seconds = encoded = submitted = pairs = 0
    for match in metrics.finditer(log):
        input_fps, submitted_fps, dropped_fps, encoded_fps = map(float, match.group(1, 2, 3, 4))
        count = int(match[5])
        if previous is not None and first['pairs'] <= previous <= count <= last['pairs']:
            checks.require(count > previous and input_fps > 0 and dropped_fps == 0, 'server_window_continuity', count)
            if input_fps > 0:
                span = (count - previous) / input_fps
                seconds += span
                pairs += count - previous
                encoded += encoded_fps * span
                submitted += submitted_fps * span
                windows += 1
        previous = count
    checks.require(windows > 0 and seconds >= max(0, minimum - 15), 'whole_log_coverage', seconds)
    if seconds:
        checks.require(all(29.7 <= count / seconds <= 30.3 for count in (pairs, submitted, encoded)),
                       'whole_log_capture_encode_rate')
    checks.require('capture_health ' not in log, 'no_capture_health_event')
    return dict(samples=samples, duration_s=duration, service=provenance['service'],
        complete_log_windows=windows, log_duration_s=seconds, capture_fps=pairs / seconds if seconds else 0,
        submitted_fps=submitted / seconds if seconds else 0, encoded_fps=encoded / seconds if seconds else 0)


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--minimum-seconds', type=float, default=7200)
    parser.add_argument('--trace-only', action='store_true', help='Replay a partial trace; does not accept a continuous run.')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    checks = Checks()
    provenance = json.loads((args.run / 'provenance.json').read_text())
    replay = trace(args.run / 'events.txt', int(provenance['control']['session']), checks)
    observation = None if args.trace_only else monitor(args.run, args.minimum_seconds, checks)
    if not args.trace_only:
        checks.require(all(eye['duration_s'] >= args.minimum_seconds for eye in replay['eyes'].values()), 'trace_duration')
    report = dict(passed=not checks.errors, partial_trace_only=args.trace_only, errors=dict(checks.errors),
        examples=checks.examples, trace=replay, monitor=observation,
        event_sha256=sha(args.run / 'events.txt'),
        scope='Host GPIO brackets, hardware SOF/DMA identity, continuous process and complete log windows. '
              'No electrical edge, exposure-start, raw DQBUF, or frame-to-IMU association proof.')
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
