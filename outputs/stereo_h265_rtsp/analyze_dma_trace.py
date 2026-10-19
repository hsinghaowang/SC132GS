#!/usr/bin/env python3
"""Summarize software GPIO timestamps and DMA trace events; not electrical proof."""
import json
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
results = {}
for folder in sorted(root.iterdir()):
    trace = folder / 'trace.txt'
    if not trace.exists():
        continue
    edges = {}
    for line in trace.read_text().splitlines():
        match = re.search(r'(\d+\.\d+): gpio_value: (\d+)\s+set ([01])', line)
        if match:
            stamp, gpio, value = match.groups()
            edges.setdefault(gpio, []).append((float(stamp), int(value)))
    gpio_results = {}
    for gpio, values in edges.items():
        starts = [stamp for stamp, value in values if value == 0]
        periods = [b - a for a, b in zip(starts, starts[1:])]
        widths = [b[0] - a[0] for a, b in zip(values, values[1:])
                  if a[1] == 0 and b[1] == 1]
        if periods and widths:
            gpio_results[gpio] = dict(pulses=len(starts),
                min_period_us=min(periods)*1e6, max_period_us=max(periods)*1e6,
                min_pulse_us=min(widths)*1e6,
                periods_under_1ms=sum(p < .001 for p in periods))
    results[folder.name] = dict(gpio_software_timing=gpio_results,
        iommu_fault_events=trace.read_text().count(': io_page_fault:'),
        driver_queue_exhaustions=len(re.findall(r'vb2_buf_done:.*owned_by_drv = 0,', trace.read_text())))
print(json.dumps(results, indent=2))
