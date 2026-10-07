#!/usr/bin/env python3
"""Compare HDR knee response with controlled analogue gain and fixed TOTAL."""
import argparse
import binascii
import datetime
import fcntl
import hashlib
import json
import pathlib
import re
import signal
import struct
import subprocess
import time
import zlib

import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstApp', '1.0')
from gi.repository import Gst, GstApp


CAMERAS = [(18, 0x32), (16, 0x30)]
CONDITIONS = [('original-before', 2176, 57), ('unity-r2p74-before', 2176, 0),
              ('unity-r128', 47, 0), ('unity-r256', 23, 0),
              ('unity-r2p74-after', 2176, 0), ('original-after', 2176, 57)]
FRAME_BYTES = 1088 * 1280 * 5 // 4
FRAME_COUNT = 12
UNIT = 'sc132gs-hdr-rtsp.service'


def run(*args, timeout=60):
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'{args}: {result.stdout}')
    return result.stdout.strip()


def parsed(text):
    return dict(re.findall(r'(\w+)=([^\s]+)', text))


def read(bus, address, register, count=1):
    return [int(v, 16) for v in run('i2ctransfer', '-f', '-y', str(bus),
        f'w2@{address:#x}', f'{register >> 8:#x}', f'{register & 255:#x}', f'r{count}').split()]


def state(bus, address):
    total = read(bus, address, 0x3e00, 3)
    second = read(bus, address, 0x3e31, 2)
    return {'total': ((total[0] & 15) << 16) | total[1] << 8 | total[2],
        'second': second[0] << 8 | second[1], 'hdrc_ratio': read(bus, address, 0x5400)[0],
        'gain_mode': read(bus, address, 0x3e03)[0],
        'long_gain': read(bus, address, 0x3e06, 4),
        'short_gain': read(bus, address, 0x3e10, 4),
        'hdr_mode': read(bus, address, 0x3220)[0], 'hdrc_enable': read(bus, address, 0x5001)[0]}


def verify(control, reference=None):
    states = [state(*camera) for camera in CAMERAS]
    assert states[0] == states[1], states
    s = states[0]
    assert s['total'] == 0x5d40 and s['second'] == control * 4, states
    expected = (255 * (s['total'] - s['second']) + s['total'] // 2) // s['total']
    assert s['hdrc_ratio'] == expected and s['hdr_mode'] & 0x40 and s['hdrc_enable'] & 1, states
    if reference:
        for key in ('total', 'gain_mode', 'long_gain', 'short_gain', 'hdr_mode', 'hdrc_enable'):
            assert s[key] == reference[key], (key, s, reference)
    return states


def controls(paths, exposure, gain):
    for path in paths:
        run('v4l2-ctl', '-d', path, f'--set-ctrl=exposure={exposure},analogue_gain={gain}')


def chunk(kind, payload):
    body = kind + payload
    return struct.pack('>I', len(payload)) + body + struct.pack('>I', binascii.crc32(body) & 0xffffffff)


def rtsp_capture(url, output):
    pipeline = Gst.parse_launch(
        f'rtspsrc location={url} protocols=tcp latency=100 ! '
        'rtph265depay ! h265parse ! avdec_h265 ! videoconvert ! '
        'video/x-raw,format=RGB ! appsink name=frames sync=false max-buffers=2 drop=true')
    sink, bus = pipeline.get_by_name('frames'), pipeline.get_bus()
    count = 0
    assert pipeline.set_state(Gst.State.PLAYING) != Gst.StateChangeReturn.FAILURE
    deadline = time.monotonic() + 20
    try:
        while time.monotonic() < deadline:
            message = bus.pop_filtered(Gst.MessageType.ERROR)
            if message:
                raise RuntimeError(message.parse_error())
            sample = sink.try_pull_sample(200 * Gst.MSECOND)
            if sample is None:
                continue
            count += 1
            if count < 30:
                continue
            buffer = sample.get_buffer()
            caps = sample.get_caps().get_structure(0)
            width, height = caps.get_value('width'), caps.get_value('height')
            assert (width, height) == (2176, 1280)
            pixels = buffer.extract_dup(0, buffer.get_size())
            assert len(pixels) == width * height * 3
            rows = b''.join(b'\0' + pixels[y*width*3:(y+1)*width*3] for y in range(height))
            png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            output.write_bytes(png + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))
            return {'timestamp_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'width': width, 'height': height, 'decoded_frames': count,
                'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}
        raise RuntimeError('RTSP did not produce 30 decoded frames')
    finally:
        pipeline.set_state(Gst.State.NULL)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=pathlib.Path)
    parser.add_argument('--url', default='rtsp://192.168.137.226:8554/stereo')
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    Gst.init(None)
    initial_mode = parsed(run('sc132gs-ctl', 'mode'))
    initial = parsed(run('sc132gs-ctl', 'status'))
    assert initial_mode['running'] == '1'
    assert initial_mode['fps'] == ('60' if initial_mode['camera_mode'] == 'linear' else '30')
    media = run('sc132gs-discover', 'media')
    paths = [run('media-ctl', '-d', media, '-e', f'sc132gs {name}')
             for name in ('18-0032', '16-0030')]
    original_controls = [run('v4l2-ctl', '-d', p, '--get-ctrl=exposure,analogue_gain') for p in paths]
    report = {'initial_mode': initial_mode, 'initial_status': initial,
        'original_controls': original_controls, 'conditions': [],
        'method': 'Fixed TOTAL; gain 57 versus gain 0; HDR remains enabled. RAW warmup 60 then 12 complete frames/eye; RTSP sequential; repeated baselines.'}
    lock = None
    generator = None
    captures = []
    handles = []
    error = None
    try:
        print(run('sc132gs-ctl', 'set-mode', 'hdr'), flush=True)
        deadline, stable = time.monotonic() + 45, 0
        while time.monotonic() < deadline:
            s = parsed(run('sc132gs-ctl', 'status'))
            brightness = (int(s['cam0_percent']) + int(s['cam1_percent'])) / 2
            stable = stable + 1 if abs(brightness - int(s['target_percent'])) <= 2 else 0
            if s['mode'] != 'auto' or stable >= 4:
                break
            time.sleep(.5)
        else:
            raise RuntimeError(f'HDR AE did not settle: {s}')
        run('sc132gs-ctl', 'auto', 'off')
        frozen = parsed(run('sc132gs-ctl', 'status'))
        gain = int(frozen['gain_index'])
        report['fixed_gain_index'] = gain
        report['frozen_status'] = frozen
        lock = open('/run/sc132gs-mode.lock', 'a')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        controls(paths, 2176, gain)
        time.sleep(2)
        reference = verify(2176)[0]
        report['reference_registers'] = reference
        for label, control, gain in CONDITIONS:
            assert parsed(run('sc132gs-ctl', 'status'))['mode'] == 'off'
            controls(paths, control, gain)
            time.sleep(2)
            before = verify(control)
            assert before[0]['long_gain'] == ([0, 128, 3, 32] if gain == 0 else [0, 128, 35, 61]), before
            assert before[0]['short_gain'] == reference['short_gain'], before
            capture = rtsp_capture(args.url, out / f'{label}-rtsp.png')
            after = verify(control)
            assert before == after
            condition = {'label': label, 'exposure_control': control, 'gain_index': gain,
                'total_over_second': reference['total'] / (control * 4),
                'rtsp_registers_before': before, 'rtsp_registers_after': after,
                'rtsp': capture}
            report['conditions'].append(condition)
            (out / 'capture-evidence.json').write_text(json.dumps(report, indent=2) + '\n')
            print(f'RTSP {label}: ratio={condition["total_over_second"]:.4f}, gain={gain}, states={after}', flush=True)

        run('systemctl', 'stop', UNIT)
        run('configure-sc132gs-dual-pipeline')
        run('prepare-sc132gs-sync-gpios')
        fsync_log = open(out / 'fsync.log', 'w')
        handles.append(fsync_log)
        generator = subprocess.Popen(['/usr/local/bin/sc132gs-fsync-generator', 'auto',
            '18', '19', '30', '100', 'active-low'], stdout=fsync_log, stderr=subprocess.STDOUT)
        for _ in range(100):
            if 'FSYNC generator armed' in (out / 'fsync.log').read_text():
                break
            assert generator.poll() is None
            time.sleep(.05)
        else:
            raise RuntimeError('FSYNC did not arm')
        generator.send_signal(signal.SIGUSR1)
        nodes = [run('sc132gs-discover', f'cam{i}') for i in range(2)]
        for condition in report['conditions']:
            label, control, gain = condition['label'], condition['exposure_control'], condition['gain_index']
            controls(paths, control, gain)
            captures = []
            for eye, node in enumerate(nodes):
                log = open(out / f'{label}-cam{eye}.log', 'w')
                handles.append(log)
                captures.append(subprocess.Popen(['v4l2-ctl', '-d', node, '--stream-mmap=4',
                    '--stream-poll', '--stream-skip=60', f'--stream-count={FRAME_COUNT}',
                    f'--stream-to={out}/{label}-cam{eye}.raw'], stdout=log, stderr=subprocess.STDOUT))
            for camera in CAMERAS:
                for _ in range(100):
                    if read(*camera, 0x0100)[0] == 1:
                        break
                    time.sleep(.01)
                else:
                    raise RuntimeError(f'Sensor did not stream: {camera}')
            before = verify(control)
            assert before[0]['long_gain'] == ([0, 128, 3, 32] if gain == 0 else [0, 128, 35, 61]), before
            assert before[0]['short_gain'] == reference['short_gain'], before
            condition['raw_registers'] = before
            condition['raw'] = []
            condition['raw_timestamp_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            for process in captures:
                assert process.wait(timeout=15) == 0
            for eye in range(2):
                data = (out / f'{label}-cam{eye}.raw').read_bytes()
                assert len(data) == FRAME_COUNT * FRAME_BYTES, (label, eye, len(data))
                hashes = [hashlib.sha256(data[i*FRAME_BYTES:(i+1)*FRAME_BYTES]).hexdigest()
                          for i in range(FRAME_COUNT)]
                assert len(set(hashes)) == FRAME_COUNT
                condition['raw'].append({'eye': eye, 'frames': FRAME_COUNT,
                    'frame_bytes': FRAME_BYTES, 'sha256': hashes})
            (out / 'capture-evidence.json').write_text(json.dumps(report, indent=2) + '\n')
            print(f'RAW {label}: {FRAME_COUNT} complete distinct frames per eye; states={before}', flush=True)
    except BaseException as exc:
        error = exc
        report['error'] = repr(exc)
    finally:
        for process in captures:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
        if generator and generator.poll() is None:
            generator.terminate()
            generator.wait(timeout=5)
        for handle in handles:
            handle.close()
        if lock:
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()
        # A fresh service reapplies original mode tables and cached controls.
        report['restore'] = run('sc132gs-ctl', 'set-mode', initial_mode['camera_mode'])
        if initial['mode'] == 'auto':
            run('sc132gs-ctl', 'set-brightness', initial['target_percent'])
        else:
            run('sc132gs-ctl', 'auto', 'off')
            for path, text in zip(paths, original_controls):
                values = dict(re.findall(r'(exposure|analogue_gain):\s*(\d+)', text))
                run('v4l2-ctl', '-d', path,
                    f'--set-ctrl=exposure={values["exposure"]},analogue_gain={values["analogue_gain"]}')
        # Persist the restored AE preference, including early-failure paths
        # where the temporary active service reported manual AE at restore.
        report['restore_preferences'] = run('sc132gs-ctl', 'set-mode', initial_mode['camera_mode'])
        report['final_mode'] = parsed(run('sc132gs-ctl', 'mode'))
        report['final_status'] = parsed(run('sc132gs-ctl', 'status'))
        report['restored_rtsp'] = rtsp_capture(args.url, out / 'restored-rtsp.png')
        assert report['final_mode'] == initial_mode
        assert report['final_status']['mode'] == initial['mode']
        (out / 'capture-evidence.json').write_text(json.dumps(report, indent=2) + '\n')
        print('RESTORED: ' + json.dumps(report['final_mode']), flush=True)
    if error:
        raise error
    print('Complete: ' + str(out), flush=True)


if __name__ == '__main__':
    main()
