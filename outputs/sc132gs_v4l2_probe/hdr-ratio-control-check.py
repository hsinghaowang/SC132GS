#!/usr/bin/env python3
"""Verify both sensors' HDR exposure/ratio updates through the installed driver."""
import importlib
import json
import pathlib
import re
import time

h = importlib.import_module('hdr-ratio-check')


def main():
    before = h.run('sc132gs-ctl', 'status')
    assert 'camera_mode=hdr' in before
    exposure, gain = map(int, re.search(
        r'exposure_lines=(\d+) gain_index=(\d+)', before).groups())
    target = re.search(r'target_percent=(\d+)', before).group(1)
    was_auto = 'mode=auto ' in before
    media = h.run('sc132gs-discover', 'media')
    subdevs = [h.run('media-ctl', '-d', media, '-e', f'sc132gs {identity}')
               for identity in ('18-0032', '16-0030')]
    report = {'before': before, 'updates': [], 'invalid_controls': []}
    try:
        h.run('sc132gs-ctl', 'auto', 'off')
        for control in (8, 200, 808, 1492, 2176, 808, 2176):
            for subdev in subdevs:
                h.run('v4l2-ctl', '-d', subdev, f'--set-ctrl=exposure={control}')
            time.sleep(.12)  # Exposure changes latch after up to two frames.
            states = [h.registers(*camera) for camera in ((18, 0x32), (16, 0x30))]
            assert states[0] == states[1], states
            for state in states:
                total = state['total']
                expected = (255*(total-control*4) + total//2)//total
                assert state['second'] == control*4 and state['ratio'] == expected, state
            report['updates'].append({'control': control, 'registers': states})
        for eye, subdev in enumerate(subdevs):
            # VIDIOC_S_CTRL may clamp out-of-range values; assert cached controls
            # and actual register pairs remain valid regardless of return status.
            for invalid in (0, 2177):
                attempt = h.run('v4l2-ctl', '-d', subdev,
                                f'--set-ctrl=exposure={invalid}', check=False)
                cached = h.run('v4l2-ctl', '-d', subdev, '--get-ctrl=exposure')
                value = int(cached.split(':')[-1])
                assert 8 <= value <= 2176
                state = h.registers(*((18, 0x32), (16, 0x30))[eye])
                expected = (255*(state['total']-value*4) + state['total']//2)//state['total']
                assert state['second'] == value*4 and state['ratio'] == expected, state
                report['invalid_controls'].append({'subdev': subdev,
                    'input': invalid, 'result': attempt, 'cached_control': value,
                    'registers': state})
        # Bring both eyes back to the same valid setting after clamp/reject checks.
        for subdev in subdevs:
            h.run('v4l2-ctl', '-d', subdev, f'--set-ctrl=exposure={exposure}')
        states = [h.registers(*camera) for camera in ((18, 0x32), (16, 0x30))]
        assert states[0] == states[1], states
        report['restored_registers'] = states
    finally:
        for subdev in subdevs:
            h.run('v4l2-ctl', '-d', subdev,
                  f'--set-ctrl=exposure={exposure},analogue_gain={gain}', check=False)
        if was_auto:
            h.run('sc132gs-ctl', 'set-brightness', target)
        report['after'] = h.run('sc132gs-ctl', 'status')
        pathlib.Path('/home/ubuntu/sc132gs-hdrc-ratio-20261006/control-evidence.json').write_text(
            json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
