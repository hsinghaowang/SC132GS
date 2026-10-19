#!/usr/bin/env python3
"""Split saved CSID SOF/EOF duration from the VFE ISR host timestamp."""
import argparse
import json
from pathlib import Path
import statistics


def stats(values):
    return dict(count=len(values), mean_ns=statistics.fmean(values),
                stddev_ns=statistics.pstdev(values), min_ns=min(values), max_ns=max(values))


p = argparse.ArgumentParser()
p.add_argument('measurement', type=Path)
p.add_argument('output', type=Path)
a = p.parse_args()
meta = json.loads((a.measurement/'measurement.json').read_text())
result = json.loads((a.measurement/'result.json').read_text())
events = a.measurement.parent/(meta['run_name']+'-events')/'events.txt'
checks, done, frequencies = {}, [[], []], set()
for line in events.read_text().splitlines():
    if line.startswith('#'): continue
    e = list(map(int, line.split()))
    if e[2] == 8: frequencies.add(e[7])
    if e[2] == 7: checks[(e[3], e[8])] = e
    if (e[2] == 3 and e[3] in (0, 1) and e[9] == 0 and
            result['first_trigger'] <= e[5] <= result['last_trigger']):
        done[e[3]].append(e)
assert len(frequencies) == 1
frequency = frequencies.pop()
assert frequency == 19_200_000
out = dict(counter_frequency_hz=frequency, eyes={})
for eye in (0, 1):
    span, tail, to_dma = [], [], []
    for e in done[eye]:
        check = checks[(eye, e[8])]
        assert check[9] == 0 and check[1] == e[1] and check[7] >= e[6]
        duration = (check[7]-e[6])*1_000_000_000/frequency
        span.append(duration)
        to_dma.append(e[4]-e[7])
        tail.append(e[4]-e[7]-duration)
    assert len(span) == result['matched_triggers']
    out['eyes'][str(eye)] = dict(hardware_SOF_to_EOF=stats(span),
                               mapped_SOF_to_DMA_ISR=stats(to_dma),
                               DMA_ISR_minus_mapped_EOF=stats(tail))
out['limitations'] = [
    'CSID packet/frame markers are not independently verified exposure boundaries',
    'host and hardware clock mapping uncertainty is included in the signed EOF-to-ISR residual',
    'SOF-to-EOF measures the whole CSI-2 frame span, not only active serialized bits']
a.output.write_text(json.dumps(out, indent=2)+'\n')
print(json.dumps(out, indent=2))
