#!/usr/bin/env python3
"""Board-only fixed-exposure RAW A/B/A check; restore the original stream."""
import argparse
import fcntl
import hashlib
import json
import pathlib
import re
import signal
import subprocess
import time


def run(*args, check=True, timeout=45):
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f'{args}: {result.stdout}')
    return result.stdout.strip()


def read(bus, address, register, count=1):
    return [int(value, 16) for value in run(
        'i2ctransfer', '-f', '-y', str(bus), f'w2@{address:#x}',
        f'{register >> 8:#x}', f'{register & 255:#x}', f'r{count}').split()]


def write(bus, address, register, value):
    run('i2ctransfer', '-f', '-y', str(bus), f'w3@{address:#x}',
        f'{register >> 8:#x}', f'{register & 255:#x}', f'{value:#x}')


def registers(bus, address):
    total = read(bus, address, 0x3e00, 3)
    second = read(bus, address, 0x3e31, 2)
    return {'total': ((total[0] & 15) << 16) | total[1] << 8 | total[2],
            'second': second[0] << 8 | second[1],
            'ratio': read(bus, address, 0x5400)[0],
            'gain': read(bus, address, 0x3e08, 2)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=pathlib.Path)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    lock = open('/run/sc132gs-mode.lock', 'a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    report = {'before': run('sc132gs-ctl', 'status'), 'conditions': []}
    assert 'camera_mode=hdr' in report['before']
    was_auto = 'mode=auto ' in report['before']
    controls = re.search(r'exposure_lines=(\d+) gain_index=(\d+)', report['before'])
    exposure, gain = map(int, controls.groups())
    media = run('sc132gs-discover', 'media')
    subdevs = [run('media-ctl', '-d', media, '-e', f'sc132gs {identity}')
               for identity in ('18-0032', '16-0030')]
    buses = [(18, 0x32), (16, 0x30)]
    generator = None
    handles = []
    captures = []
    try:
        run('systemctl', 'stop', 'sc132gs-hdr-rtsp.service')
        run('configure-sc132gs-dual-pipeline')
        run('prepare-sc132gs-sync-gpios')
        log = open(out / 'fsync.log', 'w')
        handles.append(log)
        generator = subprocess.Popen(
            ['/usr/local/bin/sc132gs-fsync-generator', 'auto', '18', '19',
             '30', '100', 'active-low'], stdout=log, stderr=subprocess.STDOUT)
        for _ in range(100):
            if 'FSYNC generator armed' in (out / 'fsync.log').read_text():
                break
            assert generator.poll() is None
            time.sleep(.05)
        else:
            raise RuntimeError('FSYNC did not arm')
        generator.send_signal(signal.SIGUSR1)
        nodes = [run('sc132gs-discover', f'cam{i}') for i in range(2)]
        for label, override in [('a-before', 0x80), ('b-formula', None),
                                ('a-after', 0x80)]:
            for subdev in subdevs:
                run('v4l2-ctl', '-d', subdev,
                    f'--set-ctrl=exposure={exposure},analogue_gain={gain}')
            captures = []
            for eye, node in enumerate(nodes):
                log = open(out / f'{label}-cam{eye}.log', 'w')
                handles.append(log)
                captures.append(subprocess.Popen(
                    ['v4l2-ctl', '-d', node, '--stream-mmap=4', '--stream-poll',
                     '--stream-skip=60', '--stream-count=12',
                     f'--stream-to={out}/{label}-cam{eye}.raw'],
                    stdout=log, stderr=subprocess.STDOUT))
            # STREAMON writes the full table, so override only after both streams start.
            for bus, address in buses:
                for _ in range(100):
                    if read(bus, address, 0x0100)[0] == 1:
                        break
                    time.sleep(.01)
                else:
                    raise RuntimeError('sensor did not stream')
                state = registers(bus, address)
                ratio = (255 * (state['total'] - state['second']) +
                         state['total'] // 2) // state['total']
                write(bus, address, 0x5400, ratio if override is None else override)
            state = [registers(*camera) for camera in buses]
            assert state[0] == state[1], state
            for process in captures:
                assert process.wait(timeout=15) == 0
            condition = {'label': label, 'exposure_control': exposure,
                         'gain_index': gain, 'registers': state, 'raw': []}
            for eye in range(2):
                raw = (out / f'{label}-cam{eye}.raw').read_bytes()
                size = 1088 * 1280 * 5 // 4
                assert len(raw) == 12 * size, (eye, len(raw))
                hashes = [hashlib.sha256(raw[i*size:(i+1)*size]).hexdigest()
                          for i in range(12)]
                assert len(set(hashes)) == 12
                condition['raw'].append({'eye': eye, 'frame_bytes': size,
                                         'frames': 12, 'hashes': hashes})
            report['conditions'].append(condition)
            (out / 'capture-evidence.json').write_text(json.dumps(report, indent=2))
            print(f'{label}: {state}', flush=True)
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
        for subdev in subdevs:
            run('v4l2-ctl', '-d', subdev,
                f'--set-ctrl=exposure={exposure},analogue_gain={gain}', check=False)
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
        report['restore'] = run('sc132gs-ctl', 'set-mode', 'hdr')
        if not was_auto:
            run('sc132gs-ctl', 'auto', 'off')
            for subdev in subdevs:
                run('v4l2-ctl', '-d', subdev,
                    f'--set-ctrl=exposure={exposure},analogue_gain={gain}')
        report['after'] = run('sc132gs-ctl', 'status')
        (out / 'capture-evidence.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
