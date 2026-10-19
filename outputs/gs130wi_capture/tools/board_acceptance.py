#!/usr/bin/env python3
"""Finite acceptance on the named RUBIK board, restoring the original owner in finally."""
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import time

ROOT = Path('/home/ubuntu/capture-api-20261015')
OUT = ROOT / 'evidence'
UNIT = 'sc132gs-camera-rtsp.service'
CONTROL = Path('/sys/bus/platform/devices/acb3000.camss/fsync_control')


def run(args, name=None, **kwargs):
    if name:
        with (OUT / name).open('w') as output:
            return subprocess.run(args, stdout=output, stderr=subprocess.STDOUT, check=True, **kwargs)
    return subprocess.check_output(args, text=True, **kwargs)


def pulse_start():
    CONTROL.write_text('stop\n')
    CONTROL.write_text('start\n')


def snapshot(name):
    run(['python3', str(ROOT / 'outputs/gs130wi_imu/snapshot_registers.py')], name)


def profile_hashes():
    names = ['/var/lib/sc132gs-camera/settings.json', '/var/lib/sc132gs-camera/settings.yaml',
             '/home/ubuntu/stereo-h265-rtsp/run-camera-profile.sh',
             '/home/ubuntu/stereo-h265-rtsp/run-stereo-rtsp.sh',
             '/home/ubuntu/stereo-h265-rtsp/build-main10/stereo-h265-rtsp']
    return {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in names}


def main():
    OUT.mkdir(exist_ok=True)
    if run(['systemctl', 'is-active', UNIT]).strip() != 'active':
        raise RuntimeError('expected active original camera owner')
    environment = shlex.split(run(['systemctl', 'show', UNIT, '--property=Environment', '--value']))
    if not {'BINNING=0', 'FPS=30', 'SENSOR_MODE=linear'}.issubset(environment):
        raise RuntimeError('unexpected production profile; refusing to stop')
    run(['systemctl', 'cat', UNIT], 'original-unit.txt')
    before = profile_hashes()
    (OUT / 'profile-hashes-before.json').write_text(json.dumps(before, indent=2))
    snapshot('imu-before.json')
    run(['dmesg'], 'dmesg-before.txt')
    cpus = run(['python3', '/home/ubuntu/sc132gs-kernel-sync-20261014/camera_cpu_list.py']).strip()
    (OUT / 'consumer-cpus.txt').write_text(cpus + '\n')
    rtsp = None
    try:
        run(['systemctl', 'stop', UNIT])
        pulse_start()
        run(['taskset', '--cpu-list', cpus, str(ROOT / 'build/gs130wi-capture-probe'),
             '300', str(OUT / 'api')], 'api-probe.log', timeout=30)
        snapshot('imu-after-api.json')
        pulse_start()
        docker = ['docker', 'run', '--rm', '--name', 'gs130wi-ros-acceptance-20261015',
                  '--network', 'host', '--user', '0', '--cpuset-cpus', cpus, '-e', 'ROS_DOMAIN_ID=65',
                  '-v', str(ROOT) + ':/work', '-v', '/run/lock:/run/lock']
        for device in ['/dev/video0', '/dev/video3', '/dev/i2c-18', '/dev/gpiochip4']:
            docker += ['--device', device]
        docker += ['rubikpi/ros2-humble:local', 'bash', '/work/ros_live_test.sh']
        run(docker, 'ros-live.log', timeout=45)
        snapshot('imu-after-ros.json')
        pulse_start()
        command = ['taskset', '--cpu-list', cpus, str(ROOT / 'build-rtsp/stereo-h265-rtsp'), '--cam0', '/dev/video0', '--cam1', '/dev/video3',
                   '--bind', '192.168.137.226', '--port', '8555', '--mount', '/stereo', '--downscale', '1',
                   '--fps', '30', '--auto-exposure', 'off', '--hevc-profile', 'main10',
                   '--bitrate', '10000000', '--capture-api', 'on']
        with (OUT / 'rtsp-api.log').open('w') as output:
            rtsp = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT)
            for _ in range(100):
                if rtsp.poll() is not None:
                    raise RuntimeError('API RTSP server exited during startup')
                if 'Capture ready:' in (OUT / 'rtsp-api.log').read_text():
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError('API RTSP startup timeout')
            if shutil.which('ffmpeg'):
                run(['ffmpeg', '-hide_banner', '-rtsp_transport', 'tcp', '-i', 'rtsp://192.168.137.226:8555/stereo',
                     '-frames:v', '91', '-f', 'null', '-'], 'rtsp-api-decode.log', timeout=20)
            else:
                # The Windows verifier is already available in this workspace.
                # It writes its actual decode result here; no synthetic success.
                (OUT / 'rtsp-ready.txt').write_text('rtsp://192.168.137.226:8555/stereo\n')
                completed = OUT / 'rtsp-external-decode.json'
                deadline = time.monotonic() + 90
                while not completed.exists() and time.monotonic() < deadline:
                    time.sleep(0.2)
                if not completed.exists() or not json.loads(completed.read_text())['passed']:
                    raise RuntimeError('external RTSP decode missing/failed')
            rtsp.terminate()
            if rtsp.wait(timeout=15) != 0:
                raise RuntimeError('API RTSP shutdown failed')
            rtsp = None
        snapshot('imu-after-rtsp.json')
        run(['cat', str(CONTROL)], 'sync-after-tests.txt')
    finally:
        if rtsp is not None and rtsp.poll() is None:
            rtsp.terminate()
            try:
                rtsp.wait(timeout=15)
            except subprocess.TimeoutExpired:
                rtsp.kill()
                rtsp.wait()
        # Remove a timed-out finite ROS container before restoring the owner.
        if subprocess.run(['docker', 'inspect', 'gs130wi-ros-acceptance-20261015'],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            run(['docker', 'stop', '-t', '15', 'gs130wi-ros-acceptance-20261015'])
        CONTROL.write_text('stop\n')
        restore = subprocess.run(['systemctl', 'start', UNIT], capture_output=True, text=True)
        if restore.returncode:
            args = ['systemd-run', '--unit=' + UNIT, '--property=TimeoutStopSec=15s']
            args += ['--setenv=' + value for value in environment]
            args += ['/bin/bash', '/home/ubuntu/stereo-h265-rtsp/run-camera-profile.sh']
            run(args, 'restore-owner.log')
        for _ in range(100):
            if 'running=1' in run(['cat', str(CONTROL)]) and 'Capture ready:' in Path('/run/sc132gs-camera-server.log').read_text():
                break
            time.sleep(0.1)
        snapshot('imu-final.json')
        after = profile_hashes()
        (OUT / 'profile-hashes-after.json').write_text(json.dumps(after, indent=2))
        run(['cat', str(CONTROL)], 'sync-final.txt')
        run(['dmesg'], 'dmesg-after.txt')
        if before != after:
            raise RuntimeError('original profile/binary hashes changed')
        baseline = json.loads((OUT / 'imu-before.json').read_text())
        for name in ['imu-final.json', 'imu-after-api.json', 'imu-after-ros.json', 'imu-after-rtsp.json']:
            if (OUT / name).exists() and json.loads((OUT / name).read_text()) != baseline:
                raise RuntimeError('IMU restoration mismatch: ' + name)
    print('API/ROS/RTSP bounded acceptance completed; original owner and profiles restored')


if __name__ == '__main__':
    main()
