#!/usr/bin/env python3
"""Check durable record validation without touching camera hardware."""
import importlib.util
import json
from pathlib import Path
import tempfile

spec=importlib.util.spec_from_file_location('platform_adapter',Path(__file__).with_name('camera_platform.py'))
adapter=importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)
valid=dict(schema=1,mode='linear',binning=1,max_fps=60,fps=60,ae=1,brightness=40,
    rows=2560,gain=1,max_exposure_us=0,max_gain_index=128,revision=12)
adapter.validate_record(valid)
invalid=(dict(schema=2),dict(binning=2),dict(mode='hdr'),dict(max_fps=50),
    dict(fps=120),dict(ae=0,rows=2561),dict(ae=0,max_exposure_us=8000),dict(gain=129),
    dict(ae=True),dict(brightness=-1),dict(brightness=101),dict(revision=-1))
for patch in invalid:
    try: adapter.validate_record(dict(valid,**patch))
    except adapter.Failure: continue
    raise AssertionError('accepted invalid record '+str(patch))
# AE startup seeds from a slower profile are narrowed to the new deadline.
# Manual exposures outside that deadline must still be rejected above.
automatic=dict(valid,rows=2561)
adapter.validate_record(automatic)
assert automatic['rows']==2560
automatic=dict(valid,max_exposure_us=8000)
adapter.validate_record(automatic)
assert automatic['rows']==1296
hdr=dict(valid,mode='hdr',binning=0,fps=30,rows=1000,gain=0,max_gain_index=0)
adapter.validate_record(hdr)
adapter.validate_record(dict(hdr,gain=16,max_gain_index=16))
for brightness in (0,100): adapter.validate_record(dict(hdr,brightness=brightness))
with tempfile.TemporaryDirectory() as directory:
    path=Path(directory)/'settings.json'
    adapter.atomic_record(path,valid)
    assert json.loads(path.read_text())==valid
    adapter.atomic_record(path,hdr)
    assert json.loads(path.read_text())==hdr
    assert not path.with_suffix('.tmp').exists()
    path=Path(directory)/'settings.yaml'
    adapter.atomic_record(path,valid)
    assert 'ae: true' in path.read_text()
    assert adapter.load_durable(path)==valid
    for text in ('mode: linear\nmode: hdr\n','- linear\n- hdr\n',
                 '!!python/object/apply:os.system [false]',path.read_text()+'unknown: 1\n'):
        path.write_text(text)
        try: adapter.load_durable(path)
        except adapter.Failure: continue
        raise AssertionError('accepted invalid YAML')
    adapter.DURABLE=path
    adapter.LEGACY_DURABLE=path.with_suffix('.json')
    path.unlink()
    adapter.LEGACY_DURABLE.write_text(json.dumps(valid))
    assert adapter.durable_record()==valid
    assert path.exists() and adapter.LEGACY_DURABLE.exists()
    path.write_text('mode: invalid\n')
    try: adapter.durable_record()
    except adapter.Failure: pass
    else: raise AssertionError('invalid YAML fell back to old JSON')
print('persistence validation and atomic replacement passed')
