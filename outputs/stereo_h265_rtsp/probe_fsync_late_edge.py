#!/usr/bin/env python3
"""Reproduce the measured short-interval case in the actual absolute callback.

Only GPIO/clock/publication are mocked. A 700 us late assertion followed by an
on-time slot must not replay the short interval observed before a trigger gap.
This is a source regression probe, not an electrical or sensor measurement.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess


def extract(source, signature):
    start = source.index(signature)
    opening = source.index('{', start)
    depth = 1
    for end in range(opening + 1, len(source)):
        depth += (source[end] == '{') - (source[end] == '}')
        if not depth:
            return source[start:end + 1]
    raise ValueError(signature)


TEST = r'''
int main(void) {
    struct camss_sync s = {0};
    s.running = true;
    s.epoch = s.next = s.timer.expires = 1000000000ULL;
    gpio_error = 0;
    now = s.next + 700000;
    enum hrtimer_restart status = tick(&s.timer);
    require(s.epoch == 1000000000ULL);
    if (!asserts) {
        printf("{\"passed\":true,\"first_assertion_skipped\":true,"
               "\"next_deadline_ns\":%llu,\"callback_status\":%d}\n",
               (unsigned long long)s.next, status);
        return 0;
    }
    u64 first = last_assert;
    now = s.timer.expires;
    require(tick(&s.timer) == HRTIMER_RESTART);
    now = s.timer.expires;
    require(tick(&s.timer) == HRTIMER_RESTART);
    require(asserts == 2 && last_assert > first);
    u64 interval = last_assert - first;
    /* Previous board evidence: 15,984,272 ns preceded both-eye trigger gap.
     * Reject recreating an interval at least that short. No claim is made
     * about the full range of sensor-acceptable intervals. */
    printf("{\"passed\":%s,\"first_assertion_skipped\":false,"
           "\"late_by_ns\":700000,\"assertion_interval_ns\":%llu,"
           "\"observed_bad_interval_ns\":15984272}\n",
           interval > 15984272 ? "true" : "false", (unsigned long long)interval);
    return 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--clock-fixture', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    source_data = args.source.read_bytes()
    source = source_data.decode()
    header_data = (args.source.parent/'camss-sync-match.h').read_bytes()
    helper = extract(header_data.decode(), 'static inline __u64 camss_sync_future_slot(')
    callback = extract(source, 'static enum hrtimer_restart tick(')
    tree = ast.parse(args.clock_fixture.read_text())
    prefix = next(ast.literal_eval(node.value) for node in tree.body
                  if isinstance(node, ast.Assign)
                  and any(isinstance(target, ast.Name) and target.id == 'prefix'
                          for target in node.targets))
    # The extracted callback uses these macros. Compile the source values,
    # rather than accidentally retaining a fixture's older 60 Hz period.
    configuration = {}
    for name in ('PERIOD_NS', 'PULSE_NS', 'LATE_BUDGET_NS'):
        pattern = rf'^#define\s+{name}\s+([0-9]+(?:ULL|UL|U|LL|L)?)\s*$'
        definitions = re.findall(pattern, source, re.MULTILINE)
        if len(definitions) != 1:
            raise ValueError(f'expected one constant definition for {name}')
        definition = definitions[0]
        prefix, count = re.subn(rf'^#define\s+{name}\s+[^\n]+$',
                               lambda _: f'#define {name} {definition}',
                               prefix, flags=re.MULTILINE)
        if count != 1:
            raise ValueError(f'fixture must declare {name} once')
        configuration[name] = int(definition.rstrip('UL'))
    (args.output/'camss-sync.c').write_bytes(source_data)
    (args.output/'camss-sync-match.h').write_bytes(header_data)
    fixture = args.output/'fixture.c'
    fixture.write_text(prefix + '\n' + helper + '\n' + callback + '\n' + TEST)
    executable = args.output/'fixture'
    subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                    str(fixture), '-o', str(executable)], check=True)
    run = subprocess.run([str(executable.resolve())], text=True, capture_output=True, check=True)
    result = json.loads(run.stdout)
    result.update(scope='actual callback, mocked clock/GPIO/publication; no hardware proof',
                  source_sha256=hashlib.sha256(source_data).hexdigest(),
                  callback_sha256=hashlib.sha256(callback.encode()).hexdigest(),
                  configuration_ns=configuration)
    (args.output/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['passed'] else 1)


if __name__ == '__main__':
    main()
