#!/usr/bin/env python3
"""Finite board regressions after accepted long-run evidence; restore the original owner in finally."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import signal
import subprocess
import time
from audit_stability import Checks, trace

ROOT = Path('/home/ubuntu/sc132gs-stability-20261015')
CAPTURE = Path('/home/ubuntu/capture-api-20261015')
LEGACY = Path('/home/ubuntu/sc132gs-kernel-sync-20261014')
OUT = ROOT / 'followup'
CONTROL = Path('/sys/bus/platform/devices/acb3000.camss/fsync_control')
UNIT = 'sc132gs-camera-rtsp.service'
RESTORE = 'sc132gs-camera-restore.service'
CONTAINER = 'sc132gs-ros-stability-20261015'
TASK = '01a13d90-0a97-7db3-9f2a-c00efdef30aa'


def read_fields(path):
    return dict(token.split('=', 1) for token in Path(path).read_text().split())


def run(command, *, output=None, check=True, timeout=30):
    if output:
        with Path(output).open('w') as stream:
            result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
    else:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        # Do not include full command arguments: service environments may hold credentials.
        raise RuntimeError(f'{Path(command[0]).name} failed with exit {result.returncode}')
    return result


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def gates():
    result = run(['systemctl', 'show', 'sc132gs-stability-long-20261015.service',
                  '--property=ActiveState,MainPID,LoadState'], check=False)
    state = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    terminal = state.get('ActiveState') in ('inactive', 'failed') and state.get('MainPID') == '0'
    missing = state.get('LoadState') == 'not-found' and state.get('ActiveState') == 'inactive'
    require(terminal or missing,
            'the long-run process is still active; no hardware changes allowed')
    for filename in ('result.json', 'event-audit.json', 'imu-audit.json'):
        path = ROOT / 'long-run' / filename
        require(path.exists(), 'missing completed long-run evidence: ' + filename)
        result = json.loads(path.read_text())
        require(result.get('passed') and not result.get('partial_trace_only'), 'long-run evidence failed: ' + filename)
    require(json.loads((ROOT / 'long-run/result.json').read_text())['elapsed_s'] >= 7200, 'long-run duration too short')
    run(['python3', str(ROOT / 'verify_stability_sources.py')])
    deployed = json.loads((ROOT / 'deployed-manifest.json').read_text())
    require(Path('/sys/module/qcom_camss/srcversion').read_text().strip() == deployed['module_srcversion'],
            'unexpected loaded kernel module')
    require(run(['systemctl', 'is-active', UNIT], check=False).returncode == 0, 'original RTSP owner is not active')
    require(read_fields(CONTROL)['error'] == '0', 'original capture is unhealthy')
    require(run(['docker', 'inspect', CONTAINER], check=False).returncode != 0, 'regression container name already exists')


class Regressions:
    def __init__(self):
        self.children = []
        self.files = []
        self.results = {}
        self.cpus = run(['python3', str(LEGACY / 'camera_cpu_list.py')]).stdout.strip()
        baseline = json.loads((ROOT / 'baseline-manifest.json').read_text())
        self.hashes = {name: value['sha256'] for name, value in baseline.items()
                       if not name.startswith('/boot/') and not name.endswith('qcom-camss.ko')}
        self.boot = Path('/proc/sys/kernel/random/boot_id').read_text()
        self.module = Path('/sys/module/qcom_camss/srcversion').read_text()
        self.check_hashes()

    def check_hashes(self):
        require(all(sha(path) == value for path, value in self.hashes.items()), 'persistent configuration/binary changed')

    def phase(self, name, **values):
        (OUT / 'progress.json').write_text(json.dumps(dict(phase=name, **values), indent=2) + '\n')

    def spawn(self, command, log):
        stream = Path(log).open('w')
        self.files.append(stream)
        child = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT)
        self.children.append(child)
        return child

    def stop(self, child):
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=10)
                raise RuntimeError('test child required SIGKILL; restoration needs review')
        return child.returncode

    def pulse_start(self):
        CONTROL.write_text('stop\n')
        CONTROL.write_text('start\n')
        return read_fields(CONTROL)['session']

    def snapshot(self, output):
        run(['python3', str(CAPTURE / 'outputs/gs130wi_imu/snapshot_registers.py')], output=output)

    def wait_ready(self, child, session, log=None):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            require(child.poll() is None, 'test client exited during startup')
            state = read_fields(CONTROL)
            require(state['session'] == session and state['error'] == '0', 'capture failed during startup')
            if state['locked_mask'] == '3' and state['running'] == '1' and (log is None or 'Capture ready:' in log.read_text()):
                return
            time.sleep(0.1)
        raise RuntimeError('capture startup timeout')

    def collect(self, name, seconds):
        directory = OUT / (name + '-events')
        child = self.spawn(['taskset', '-c', self.cpus, 'python3', str(ROOT / 'collect_events.py'),
                            str(directory), '--seconds', str(seconds)], OUT / (name + '-collector.log'))
        return child, directory

    def finish_trace(self, collector, directory, *, expected_fault=False):
        require(self.stop(collector) == 0, 'trace collector failed')
        run(['python3', str(ROOT / 'finalize_events.py'), str(directory)])
        record = json.loads((directory / 'collection.json').read_text())
        require(record['lost'] == 0 and record['boot_id'] == record['boot_id_final'], 'trace loss or reboot')
        if not expected_fault:
            checks = Checks()
            replay = trace(directory / 'events.txt', record['session'], checks)
            (directory / 'replay.json').write_text(json.dumps(dict(passed=not checks.errors,
                errors=dict(checks.errors), examples=checks.examples, trace=replay), indent=2) + '\n')
            require(not checks.errors, 'independent trace replay failed')

    def observe(self, child, name, session, seconds, *, finite=False):
        start = time.monotonic()
        previous = read_fields(CONTROL)
        previous_at = start
        with (OUT / (name + '-samples.jsonl')).open('w') as stream:
            while True:
                now = time.monotonic()
                elapsed = now - start
                state = read_fields(CONTROL)
                require(state['session'] == session and state['error'] == '0' and state['skipped'] == '0',
                        'invalid capture synchronization state')
                require(Path('/proc/sys/kernel/random/boot_id').read_text() == self.boot and
                        Path('/sys/module/qcom_camss/srcversion').read_text() == self.module, 'boot/module changed')
                if int(state['pulses']) > int(previous['pulses']):
                    previous_at = now
                require(now - previous_at < 15 or (finite and elapsed > seconds - 15), 'capture progress stalled')
                require((state['running'] == '1' and state['locked_mask'] == '3') or
                        (finite and elapsed > seconds - 15), 'capture stopped before the planned end')
                rss = None
                status = Path(f'/proc/{child.pid}/status')
                if status.exists():
                    match = re.search(r'^VmRSS:\s+(\d+)', status.read_text(), re.M)
                    rss = int(match[1]) if match else None
                stream.write(json.dumps(dict(elapsed_s=elapsed, pid=child.pid, rss_kib=rss, control=state)) + '\n')
                stream.flush()
                self.phase(name, elapsed_s=elapsed, child_pid=child.pid, pulses=int(state['pulses']))
                if child.poll() is not None:
                    require(finite and child.returncode == 0 and elapsed >= seconds - 15, 'test client exited early or failed')
                    break
                if not finite and elapsed >= seconds:
                    break
                require(elapsed < seconds + 30, 'finite test exceeded its deadline')
                previous = state
                time.sleep(5)
        return time.monotonic() - start

    def raw(self, name, seconds, *, reverse=False, starve=False, minimum_seconds=None):
        self.phase(name)
        session = self.pulse_start()
        collector, events = self.collect(name, seconds + 10)
        devices = ['/dev/video3', '/dev/video0'] if reverse else ['/dev/video0', '/dev/video3']
        raw = OUT / (name + '-raw')
        child = self.spawn(['taskset', '-c', self.cpus, str(LEGACY / 'raw-sync-probe'),
                            *devices, str(raw), str(seconds)], OUT / (name + '.log'))
        if starve:
            self.wait_ready(child, session)
            time.sleep(3)
            before = read_fields(CONTROL)
            child.send_signal(signal.SIGSTOP)
            try:
                time.sleep(1)
                paused = read_fields(CONTROL)
                require(before['error'] == '0' and paused['error'] == '9' and paused['running'] == '1' and
                        int(paused['pulses']) > int(before['pulses']), 'starvation was not fail-closed')
            finally:
                child.send_signal(signal.SIGCONT)
            code = child.wait(timeout=15)
            require(code != 0, 'starved raw capture returned success')
            self.results[name] = dict(passed=True, error=9, producer_continues=True, before=before, paused=paused)
        else:
            code = child.wait(timeout=seconds + 20)
            require(code == 0, 'raw DQBUF capture failed')
        (OUT / (name + '-exit.txt')).write_text(str(code) + '\n')
        self.finish_trace(collector, events, expected_fault=starve)
        if not starve:
            command = ['python3', str(ROOT / 'analyze_buffers.py'), str(raw), str(events),
                       '--minimum-seconds', str(minimum_seconds if minimum_seconds is not None else 90 if reverse else 600)]
            if reverse:
                command += ['--swap-eyes']
            run(command, output=OUT / (name + '-analysis.log'))
            self.results[name] = json.loads((raw / 'analysis.json').read_text())

    def short_exposure(self):
        devices = []
        for client in ('18-0032', '16-0030'):
            nodes = list(Path('/sys/bus/i2c/devices', client, 'video4linux').glob('v4l-subdev*'))
            require(len(nodes) == 1, 'unexpected sensor subdevice discovery')
            devices.append('/dev/' + nodes[0].name)

        def exposure(device):
            text = run(['v4l2-ctl', '-d', device, '--get-ctrl=exposure']).stdout
            match = re.search(r'exposure:\s+(\d+)', text)
            require(match is not None, 'missing exposure readback')
            return int(match[1])

        original = {device: exposure(device) for device in devices}
        record = dict(before=original, requested_rows=8)
        first_child = len(self.children)
        try:
            for device in devices:
                run(['v4l2-ctl', '-d', device, '--set-ctrl=exposure=8'])
            record['short_readback'] = {device: exposure(device) for device in devices}
            require(all(value == 8 for value in record['short_readback'].values()), 'short exposure was not applied')
            self.raw('raw-short-exposure', 65, minimum_seconds=60)
        finally:
            # Close this scenario's raw client before restoring its controls.
            for child in reversed(self.children[first_child:]):
                self.stop(child)
            for device, value in original.items():
                run(['v4l2-ctl', '-d', device, '--set-ctrl=exposure=' + str(value)])
            record['restored'] = {device: exposure(device) for device in devices}
            (OUT / 'short-exposure-controls.json').write_text(json.dumps(record, indent=2) + '\n')
            require(record['restored'] == original, 'exposure controls were not restored')

    def rtsp(self):
        name = 'rtsp-api'
        self.snapshot(OUT / (name + '-imu-before.json'))
        session = self.pulse_start()
        collector, events = self.collect(name, 1250)
        log = OUT / (name + '.log')
        child = self.spawn(['taskset', '-c', self.cpus, str(CAPTURE / 'build-rtsp/stereo-h265-rtsp'),
            '--cam0', '/dev/video0', '--cam1', '/dev/video3', '--bind', '192.168.137.226',
            '--port', '8555', '--mount', '/stereo', '--downscale', '1', '--fps', '30',
            '--auto-exposure', 'on', '--brightness', '30', '--hevc-profile', 'main10',
            '--bitrate', '10000000', '--capture-api', 'on'], log)
        self.wait_ready(child, session, log)
        elapsed = self.observe(child, name, session, 1200)
        require(self.stop(child) == 0, 'API RTSP shutdown/restore failed')
        self.finish_trace(collector, events)
        self.snapshot(OUT / (name + '-imu-after.json'))
        require(json.loads((OUT / (name + '-imu-before.json')).read_text()) ==
                json.loads((OUT / (name + '-imu-after.json')).read_text()), 'API IMU restoration mismatch')
        text = log.read_text()
        match = re.search(r'capture_api_imu samples=(\d+) fsync_packets=(\d+)', text)
        require(match is not None and int(match[1]) > 200_000 and int(match[2]) > 30_000,
                'API IMU did not deliver throughout the run')
        require('capture_health ' not in text, 'API capture health event')
        previous = 0
        seconds = encoded = submitted = 0
        windows = 0
        pattern = r'input_fps=([\d.]+) submitted_fps=([\d.]+) dropped_fps=([\d.]+) encoded_fps=([\d.]+).*?pairs=(\d+)'
        for found in re.finditer(pattern, text):
            input_fps, submitted_fps, dropped_fps, encoded_fps = map(float, found.group(1, 2, 3, 4))
            count = int(found[5])
            require(count > previous and input_fps > 0 and dropped_fps == 0, 'API server window gap/drop')
            span = (count - previous) / input_fps
            seconds += span
            encoded += span * encoded_fps
            submitted += span * submitted_fps
            previous = count
            windows += 1
        require(seconds >= 1190 and all(29.7 <= value / seconds <= 30.3 for value in
                (previous, encoded, submitted)), 'API complete-window capture/encoder coverage or rate failed')
        for number in (1, 2):
            decoded = OUT / f'rtsp-api-decode-{number:02d}.json'
            require(decoded.exists() and json.loads(decoded.read_text()).get('passed'), 'missing/failed external API RTSP decode')
        self.results[name] = dict(passed=True, elapsed_s=elapsed, imu_samples=int(match[1]), fsync_packets=int(match[2]),
            complete_log_windows=windows, log_duration_s=seconds, capture_fps=previous / seconds,
            encoded_fps=encoded / seconds, submitted_fps=submitted / seconds)

    def ros(self):
        name = 'ros'
        (OUT / name).mkdir()
        self.snapshot(OUT / (name + '-imu-before.json'))
        session = self.pulse_start()
        collector, events = self.collect(name, 650)
        command = ['docker', 'run', '--rm', '--name', CONTAINER, '--label', 'codex.task=' + TASK, '--network', 'host', '--user', '0',
                   '--cpuset-cpus', self.cpus, '-e', 'ROS_DOMAIN_ID=66', '-v', str(CAPTURE) + ':/work',
                   '-v', str(ROOT) + ':/stability', '-v', '/run/lock:/run/lock']
        for device in ('/dev/video0', '/dev/video3', '/dev/i2c-18', '/dev/gpiochip4'):
            command += ['--device', device]
        command += ['rubikpi/ros2-humble:local', 'bash', '/stability/ros_stability_test.sh']
        child = self.spawn(command, OUT / 'ros-container.log')
        self.wait_ready(child, session)
        self.observe(child, name, session, 600, finite=True)
        self.finish_trace(collector, events)
        self.snapshot(OUT / (name + '-imu-after.json'))
        require(json.loads((OUT / (name + '-imu-before.json')).read_text()) ==
                json.loads((OUT / (name + '-imu-after.json')).read_text()), 'ROS IMU restoration mismatch')
        subscriber = json.loads((OUT / name / 'subscriber.json').read_text())
        lines = (OUT / name / 'publisher.log').read_text().splitlines()
        publisher = next((json.loads(line) for line in reversed(lines) if line.startswith('{"passed":')), {})
        require(publisher.get('passed') and publisher.get('frames') == 18000 and subscriber.get('passed'), 'real ROS delivery failed')
        self.results[name] = dict(passed=True, publisher=publisher, subscriber=subscriber)

    def restore(self):
        cleanup_errors = []
        # A finite container owns its internal publisher, not the docker client PID.
        container = run(['docker', 'inspect', '--format', '{{index .Config.Labels "codex.task"}}', CONTAINER], check=False)
        if container.returncode == 0:
            require(container.stdout.strip() == TASK, 'refusing to stop a container owned by another task')
            run(['docker', 'stop', '-t', '15', CONTAINER], check=False)
        for child in reversed(self.children):
            try:
                self.stop(child)
            except Exception as error:
                cleanup_errors.append(str(error))
        for stream in self.files:
            stream.close()
        CONTROL.write_text('stop\n')
        run(['systemctl', 'start', RESTORE])
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            state = read_fields(CONTROL)
            if state['locked_mask'] == '3' and state['running'] == '1' and state['error'] == '0':
                break
            time.sleep(0.2)
        else:
            raise RuntimeError('original camera owner did not recover')
        require(run(['systemctl', 'is-active', UNIT], check=False).returncode == 0, 'original RTSP owner not active after restore')
        self.check_hashes()
        self.snapshot(OUT / 'imu-final.json')
        require(json.loads((OUT / 'imu-before.json').read_text()) == json.loads((OUT / 'imu-final.json').read_text()),
                'final IMU registers differ from the initial state')
        (OUT / 'control-final.txt').write_text(CONTROL.read_text())
        run(['dmesg', '--color=never'], output=OUT / 'dmesg-after.txt')
        require(not cleanup_errors, '; '.join(cleanup_errors))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Validate gates without changing the camera owner.')
    args = parser.parse_args()
    gates()
    suite = Regressions()
    if args.check:
        print('All long-run acceptance gates passed; no hardware changes made')
        return 0
    OUT.mkdir(exist_ok=False)
    suite.snapshot(OUT / 'imu-before.json')
    run(['dmesg', '--color=never'], output=OUT / 'dmesg-before.txt')
    failure = None
    try:
        run(['systemctl', 'stop', RESTORE, UNIT])
        suite.raw('raw-normal', 605)
        suite.short_exposure()
        suite.raw('raw-reverse', 95, reverse=True)
        suite.raw('raw-starvation', 30, starve=True)
        suite.rtsp()
        suite.ros()
    except Exception as error:
        failure = str(error)
    finally:
        try:
            suite.restore()
        except Exception as error:
            failure = (failure + '; ' if failure else '') + 'restore: ' + str(error)
    report = dict(passed=failure is None, failure=failure, scenarios=suite.results,
                  scope='Bounded DQBUF, reverse startup, starvation, shared API RTSP and real ROS/DDS regression; no frame-to-IMU timing proof')
    (OUT / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    suite.phase('passed' if report['passed'] else 'failed', failure=failure)
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    def interrupted(signum, frame):
        raise InterruptedError('regression suite interrupted')
    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGTERM, interrupted)
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps(dict(passed=False, failure=str(error))))
        raise SystemExit(1)
