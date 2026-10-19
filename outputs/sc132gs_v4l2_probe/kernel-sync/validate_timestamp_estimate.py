#!/usr/bin/env python3
"""Validate the common exposure-start offset against saved fixed-exposure evidence."""
import argparse
import hashlib
import json
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('model', type=Path)
p.add_argument('offset', type=int)
a = p.parse_args()
m = json.loads(a.model.read_text())
assert m['version'] == 1 and m['abi'] == 4
assert m['source'] == 'exposure_start_estimate'
assert m['physically_calibrated_exposure_start'] is False
assert m['sof_equals_exposure_end'] == 'assumed, not physically verified'
data = {}
for key, reference in m['evidence'].items():
    f = a.model.parent/reference['path']
    assert hashlib.sha256(f.read_bytes()).hexdigest() == reference['sha256']
    data[key] = json.loads(f.read_text())
r, transport = data['fixed_exposure'], data['mipi_budget']
assert r['passed'] and r['matched_triggers'] == m['matched_triggers']
assert r['rows'] == m['reference_exposure_rows'] == 1377
assert r['nominal_rows_per_second'] == m['nominal_rows_per_second'] == 84000
offsets = [r['per_eye_R_minus_Y'][eye]['mean_ns'] -
           transport['per_eye_measured_SOF_to_DMA_mean_ms'][eye]*1_000_000 -
           r['nominal_B_ns'] for eye in (0, 1)]
common = round(sum(offsets)/2)
assert 0 < common <= 16_666_666
assert common == a.offset == m['timestamp_offset_ns']
print(json.dumps(dict(valid=True, timestamp_offset_ns=common, per_eye_offset_ns=offsets)))
