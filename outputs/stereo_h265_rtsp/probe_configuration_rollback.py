#!/usr/bin/env python3
"""Live integration probe: fail one verification after a real mode apply."""
import sys
import camera_platform as platform

prior = platform.inspect()
original_verify = platform.verify
calls = 0

def fail_once(config, decoded):
    global calls
    calls += 1
    original_verify(config, decoded)
    if calls == 1:
        raise platform.Failure(4, 71)

platform.verify = fail_once
sys.argv = ['probe', 'apply', '--mode', 'linear', '--binning', '0', '--fps', '30',
            '--max-fps', '30', '--ae', '1', '--brightness', '40',
            '--exposure-us', '-1', '--hdr-total-rows', '-1', '--gain-index', '-1',
            '--max-exposure-us', '0', '--max-gain-index', '128',
            '--revision', str(prior['revision'])]
try:
    platform.main()
except SystemExit as result:
    after = platform.inspect()
    keys = ('sensor_mode','binning','fps','max_fps','ae','brightness','revision')
    if result.code == 1 and calls == 2 and all(after[k] == prior[k] for k in keys):
        print('rollback_probe=passed restored_revision='+str(after['revision']))
        platform.output(after)
        raise SystemExit(0)
    raise SystemExit(1)
raise SystemExit(1)
