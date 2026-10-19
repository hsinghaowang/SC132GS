#!/usr/bin/env python3
"""Finite board comparison with immutable backup and restoration of one owner.

Run on the board as root. This script never installs a binary, edits a profile,
reloads a driver, or invokes sc132gs-camera restore/reset. PC decoding is separate.
"""
import argparse
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time

UNIT = 'sc132gs-camera-rtsp.service'
ORIGINAL = Path('/home/ubuntu/stereo-h265-rtsp/build-main10/stereo-h265-rtsp')
WRAPPER = Path('/home/ubuntu/stereo-h265-rtsp/run-camera-profile.sh')
SYNC = Path('/sys/bus/platform/devices/acb3000.camss/fsync_control')
EVENTS = Path('/sys/kernel/debug/sc132gs_sync/events')
SERVER_LOG = Path('/run/sc132gs-camera-server.log')
RAW_PROBE = Path('/home/ubuntu/sc132gs-kernel-sync-20261014/raw-sync-probe')


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.new')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def run(args, timeout=30, check=True):
    p = subprocess.run([str(x) for x in args], capture_output=True, text=True,
                       timeout=timeout)
    if check and p.returncode:
        raise RuntimeError(f'{args!r}: exit={p.returncode}: {p.stdout}{p.stderr}')
    return p


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read(path):
    try:
        return Path(path).read_text()
    except (OSError, UnicodeError) as error:
        return 'READ_ERROR: ' + str(error)


def fields(text):
    return dict(re.findall(r'([A-Za-z_][A-Za-z0-9_]*)=([^\s]+)', text))


def sync_state():
    text = SYNC.read_text()
    return dict(raw=text.strip(), fields=fields(text))


def healthy_sync(state):
    data = state['fields']
    return data.get('running') == '1' and data.get('error') == '0'


def ctl(message='status'):
    with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as channel:
        channel.settimeout(3)
        channel.connect('/run/sc132gs-ae.sock')
        channel.sendall(message.encode())
        reply = channel.recv(16384).decode()
    if not reply.startswith('ok '):
        raise RuntimeError(reply)
    return fields(reply)


def try_ctl():
    try:
        return ctl()
    except Exception as error:
        return dict(unavailable=str(error))


def configure(seed, target=None):
    keys = ('exposure_lines', 'gain_index', 'target_percent', 'max_exposure_us', 'max_gain_index')
    values = [seed[key] for key in keys]
    if target is not None:
        values[2] = str(target)
    enabled = int(seed.get('mode') == 'auto')
    return ctl('configure-exposure ' + ' '.join(map(str, [enabled] + values)))


def unit_state():
    result = run(['systemctl', 'show', UNIT], check=False)
    return dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)


def process_identity(pid):
    path = Path('/proc') / str(pid)
    stat = (path / 'stat').read_text()
    # Fields after the parenthesized comm start with field 3; starttime is 22.
    ticks = stat[stat.rfind(')') + 2:].split()[19]
    return dict(pid=int(pid), start_ticks=ticks, exe=os.readlink(path / 'exe'),
                cmdline=(path / 'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace'))


def record_child(root, child, binary):
    # taskset execs the target in the same PID. Wait for that exec so recovery
    # never mistakes the temporary taskset image for a different process.
    deadline = time.monotonic() + 3
    expected = str(Path(binary).resolve())
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise RuntimeError('Child exited before executable identity was recorded')
        try:
            identity = process_identity(child.pid)
            if identity['exe'] == expected:
                write_json(root / 'test-child.json', identity)
                return
        except OSError:
            pass
        time.sleep(.01)
    raise RuntimeError('Child executable identity did not match expected binary')


def camera_owners():
    result = []
    for item in Path('/proc').iterdir():
        if not item.name.isdigit():
            continue
        try:
            owned = []
            for fd in (item / 'fd').iterdir():
                try:
                    target = os.readlink(fd)
                    if target in ('/dev/video0', '/dev/video3'):
                        owned.append(target)
                except OSError:
                    pass
            if owned:
                identity = process_identity(item.name)
                identity['devices'] = sorted(set(owned))
                result.append(identity)
        except OSError:
            pass
    return result


def evidence(directory, prefix):
    """Evidence failures must never prevent the subsequent restoration."""
    errors = []
    for name, path in [('sync', SYNC), ('events', EVENTS), ('server', SERVER_LOG)]:
        try:
            (directory / (prefix + '-' + name + '.txt')).write_text(read(path))
        except Exception as error:
            errors.append(str(error))
    try:
        p = run(['dmesg', '--color=never'], check=False)
        (directory / (prefix + '-dmesg.txt')).write_text(p.stdout + p.stderr)
    except Exception as error:
        errors.append(str(error))
    return errors


def baseline(root):
    return json.loads((root / 'backup/state.json').read_text())


def original_binary(root):
    return Path(baseline(root).get('restore_binary', str(ORIGINAL)))


def software_identity():
    return dict(boot_id=read('/proc/sys/kernel/random/boot_id').strip(),
                camss_srcversion=read('/sys/module/qcom_camss/srcversion').strip(),
                kernel_release=os.uname().release)


def backup(root):
    destination = root / 'backup'
    destination.mkdir(exist_ok=False)
    state = unit_state()
    environment = shlex.split(state.get('Environment', ''))
    env = dict(item.split('=', 1) for item in environment if '=' in item)
    owners = camera_owners()
    if len(owners) != 1 or set(owners[0]['devices']) != {'/dev/video0', '/dev/video3'}:
        raise RuntimeError('Backup requires one identified owner of both camera nodes')
    restore_binary = Path(owners[0]['exe'])
    comparison_map = env.get('GPU_RECTIFICATION_MAP') or '/home/ubuntu/main10-rectification-20261016/fixtures/calibration.map'
    paths = {ORIGINAL, WRAPPER, WRAPPER.parent / 'run-stereo-rtsp.sh',
             restore_binary, Path(comparison_map),
             Path('/var/lib/sc132gs-camera/settings.json'),
             Path('/var/lib/sc132gs-camera/settings.yaml')}
    if env.get('SERVER_BIN'):
        paths.add(Path(env['SERVER_BIN']))
    for item in [state.get('FragmentPath', '')] + shlex.split(state.get('DropInPaths', '')):
        if item:
            paths.add(Path(item))
    if env.get('GPU_RECTIFICATION_MAP'):
        paths.add(Path(env['GPU_RECTIFICATION_MAP']))
    if env.get('DEPTH_CALIBRATION'):
        paths.update(p for p in Path(env['DEPTH_CALIBRATION']).rglob('*') if p.is_file())
    manifest = {}
    for source in sorted(paths):
        if not source.is_file():
            raise RuntimeError('Required backup file missing: ' + str(source))
        target = destination / 'files' / str(source).lstrip('/')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        info = source.stat()
        original_hash = sha(source)
        if sha(target) != original_hash:
            raise RuntimeError('Backup hash mismatch: ' + str(source))
        manifest[str(source)] = dict(sha256=original_hash, mode=info.st_mode & 0o7777,
                                     uid=info.st_uid, gid=info.st_gid,
                                     backup=str(target.relative_to(root)),
                                     transient_unit=str(source).startswith('/run/systemd/transient/'))
    (destination / 'unit.txt').write_text(run(['systemctl', 'cat', UNIT], check=False).stdout)
    (destination / 'processes.txt').write_text(run(['ps', '-eo', 'pid,ppid,lstart,args']).stdout)
    (destination / 'listeners.txt').write_text(run(['ss', '-lntp'], check=False).stdout)
    for owner in owners:
        proc = Path('/proc') / str(owner['pid'])
        (destination / ('owner-' + str(owner['pid']) + '-environ.bin')).write_bytes((proc / 'environ').read_bytes())
        (destination / ('owner-' + str(owner['pid']) + '-cgroup.txt')).write_text(read(proc / 'cgroup'))
    result = dict(created_utc=utc(), software=software_identity(), unit=state, environment=environment,
                  restore_binary=str(restore_binary), comparison_rectification_map=comparison_map,
                  files=manifest, ae=try_ctl(), owners=owners, sync=sync_state(),
                  restoration_intent='restore original configured stream active; preserve pre-existing failure evidence')
    result['evidence_errors'] = evidence(destination, 'before')
    write_json(destination / 'state.json', result)
    print('BACKUP_READY', destination, flush=True)
    return result


def unchanged(root):
    result = {}
    for path, expected in baseline(root)['files'].items():
        # systemd may recreate a transient unit text; its semantic environment
        # and executable are separately checked after restoration.
        if expected['transient_unit']:
            continue
        try:
            info = Path(path).stat()
            result[path] = (sha(path) == expected['sha256'] and
                            (info.st_mode & 0o7777) == expected['mode'] and
                            info.st_uid == expected['uid'] and info.st_gid == expected['gid'])
        except OSError:
            result[path] = False
    return result


def stop_exact_test(root):
    record = root / 'test-child.json'
    if not record.exists():
        return
    old = json.loads(record.read_text())
    if old.get('exited'):
        return
    try:
        current = process_identity(old['pid'])
    except OSError:
        return
    if any(current[k] != old[k] for k in ('pid', 'start_ticks', 'exe')):
        raise RuntimeError('Test PID identity changed; refusing to signal reused PID')
    os.kill(current['pid'], signal.SIGTERM)
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        try:
            now = process_identity(current['pid'])
            if now['start_ticks'] != current['start_ticks']:
                return
        except OSError:
            return
        time.sleep(.2)
    os.kill(current['pid'], signal.SIGKILL)


def start_original(root):
    saved = baseline(root)
    expected_env = dict(value.split('=', 1) for value in saved['environment'] if '=' in value)
    expected_mode = 'auto' if expected_env.get('AUTO_EXPOSURE', '0') == '1' else 'off'
    expected_target = str(int(expected_env.get('BRIGHTNESS', '30')))
    seed = saved_seed(root)
    accepted_states = {(expected_mode, expected_target)}
    if seed:
        accepted_states.add((seed.get('mode'), seed.get('target_percent')))
    p = run(['systemctl', 'start', UNIT], timeout=35, check=False)
    if p.returncode:
        state = unit_state()
        if state.get('LoadState') != 'not-found':
            raise RuntimeError('Original service start failed: ' + p.stdout + p.stderr)
        run(['systemd-run', '--unit=' + UNIT, '--property=TimeoutStopSec=15s',
             '--property=Restart=no'] + ['--setenv=' + value for value in saved['environment']] +
            ['/bin/bash', str(WRAPPER)], timeout=35)
    deadline = time.monotonic() + 75
    while time.monotonic() < deadline:
        state = unit_state()
        if state.get('ActiveState') == 'failed':
            raise RuntimeError('Original service entered failed state')
        if state.get('ActiveState') == 'active' and healthy_sync(sync_state()):
            text = read(SERVER_LOG)
            if 'Capture ready:' in text and 'input_fps=' in text:
                try:
                    current = ctl()
                except (OSError, RuntimeError):
                    current = {}
                # The wrapper enables AE after the same first-frame marker.
                # A responsive socket alone can still expose its manual seed.
                if (current.get('mode'), current.get('target_percent')) in accepted_states:
                    return current
        time.sleep(.3)
    raise RuntimeError('Original service readiness timed out')


def saved_seed(root):
    recovered = root / 'recovered-state.json'
    if recovered.exists():
        return json.loads(recovered.read_text())['ae']
    initial = baseline(root)['ae']
    return initial if 'unavailable' not in initial else None


def restore_startup_settings_record(root, attempt):
    # The profile launcher persists the current controls on startup. Keep the
    # pre-test on-disk record (which may differ from live auto-exposure rows).
    # Never overwrite changes to any non-runtime setting.
    path = Path('/var/lib/sc132gs-camera/settings.yaml')
    meta = baseline(root)['files'][str(path)]
    if sha(path) == meta['sha256']:
        return
    saved = root / meta['backup']
    current_bytes, saved_bytes = path.read_bytes(), saved.read_bytes()
    def stable(data):
        return [line for line in data.splitlines() if not re.match(rb'^(rows|gain|revision):', line)]
    if stable(current_bytes) != stable(saved_bytes):
        raise RuntimeError('Non-runtime persistent settings changed; refusing to overwrite')
    name = 'startup-settings-attempt-' + str(attempt) + '-' + str(time.time_ns())
    (root / (name + '.yaml')).write_bytes(current_bytes)
    write_json(root / (name + '.json'), dict(time_utc=utc(), reason='restore pre-test record after profile startup',
               previous_sha256=sha(path), restored_sha256=meta['sha256']))
    temporary = path.with_name(path.name + '.raw10-tone-restore.tmp')
    shutil.copy2(saved, temporary)
    os.chown(temporary, meta['uid'], meta['gid'])
    os.chmod(temporary, meta['mode'])
    if path.read_bytes() != current_bytes:
        temporary.unlink()
        raise RuntimeError('Persistent settings changed during restoration')
    os.replace(temporary, path)


def restore(root, external=False):
    if external and (root / 'suite-unit.txt').exists():
        suite = (root / 'suite-unit.txt').read_text().strip()
        if not re.fullmatch(r'[A-Za-z0-9_.@-]+\.service', suite) or suite == UNIT:
            raise RuntimeError('Invalid task-owned suite unit')
        # Stop before taking the lock: suite SIGTERM runs the same restoration.
        run(['systemctl', 'stop', suite], timeout=180, check=False)
    with (root / 'restore.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        result = dict(started_utc=utc(), passed=False, attempts=[])
        try:
            stop_exact_test(root)
            seed = saved_seed(root)
            for attempt in range(1, 4):
                item = dict(attempt=attempt, started_utc=utc())
                try:
                    # An already restored active owner is idempotently verified.
                    active = unit_state().get('ActiveState') == 'active'
                    if not (active and healthy_sync(sync_state())):
                        run(['systemctl', 'stop', UNIT], timeout=35, check=False)
                        SYNC.write_text('stop\n')
                        run(['systemctl', 'reset-failed', UNIT], check=False)
                    current = start_original(root)
                    if seed:
                        current = configure(seed)
                    time.sleep(1)
                    current = ctl()
                    restore_startup_settings_record(root, attempt)
                    checks = unchanged(root)
                    owners = camera_owners()
                    expected_exe = str(original_binary(root).resolve())
                    owned_nodes = {node for owner in owners for node in owner['devices']}
                    expected_owners = (owned_nodes == {'/dev/video0', '/dev/video3'} and
                                       all(o['exe'] == expected_exe for o in owners))
                    live = unit_state()
                    actual_env = dict(x.split('=', 1) for x in shlex.split(live.get('Environment', '')) if '=' in x)
                    expected_env = dict(x.split('=', 1) for x in baseline(root)['environment'] if '=' in x)
                    env_ok = actual_env == expected_env
                    ae_ok = True
                    if seed:
                        keys = ['mode', 'target_percent', 'max_exposure_us', 'max_gain_index']
                        if seed.get('mode') != 'auto':
                            keys += ['exposure_lines', 'gain_index']
                        ae_ok = all(current.get(k) == seed.get(k) for k in keys)
                    control_ok = current.get('error_errno', '0') == '0'
                    passed = (all(checks.values()) and expected_owners and env_ok and ae_ok and control_ok and
                              live.get('ActiveState') == 'active' and healthy_sync(sync_state()))
                    item.update(passed=passed, ae=current, owners=owners, files_unchanged=checks,
                                environment_matches=env_ok, runtime_ae_matches=ae_ok,
                                control_error_free=control_ok, sync=sync_state())
                    if not passed:
                        raise RuntimeError('Original stream restoration verification failed')
                    result['attempts'].append(item)
                    result.update(passed=True, ae=current, completed_utc=utc(),
                                  proof='owner/configuration/FSYNC/runtime control; independent client decode still required')
                    write_json(root / 'restoration.json', result)
                    evidence(root, 'restored')
                    print('ORIGINAL_RESTORED', json.dumps(result), flush=True)
                    return result
                except Exception as error:
                    item['error'] = str(error)
                    result['attempts'].append(item)
                    evidence(root, 'restore-attempt-' + str(attempt))
                    write_json(root / 'restoration.json', result)
                    run(['systemctl', 'stop', UNIT], timeout=35, check=False)
                    time.sleep(1)
            raise RuntimeError('Original stream restoration failed after three attempts')
        except BaseException as error:
            result.update(error=str(error), completed_utc=utc())
            write_json(root / 'restoration.json', result)
            raise


def recover(root):
    result = restore(root)
    # This seed is the actual recovered owner's AE state, not stale settings.json.
    recovered = dict(time_utc=utc(), ae=ctl(), unit=unit_state(), sync=sync_state(),
                     original_failure_preserved=True)
    write_json(root / 'recovered-state.json', recovered)
    return result


def stop_child(child, root):
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=25)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)
    record = root / 'test-child.json'
    if record.exists():
        value = json.loads(record.read_text())
        value.update(exited=True, exit_code=child.returncode, exited_utc=utc())
        write_json(record, value)
    return child.returncode


def phase(root, name, seconds, seed, camera_cpus='1-6'):
    out = root / name
    out.mkdir(exist_ok=False)
    original = name == 'old_main10'
    shared = name == 'shared8'
    binary = ORIGINAL if original else root / 'build/stereo-h265-rtsp'
    env = dict(x.split('=', 1) for x in baseline(root)['environment'] if '=' in x)
    command = ['taskset', '--cpu-list', camera_cpus, str(binary), '--cam0', '/dev/video0',
               '--cam1', '/dev/video3', '--bind', '192.168.137.226', '--port', '8554',
               '--mount', '/stereo', '--downscale', '1', '--fps', '30',
               '--brightness', '30', '--auto-exposure', 'off', '--hevc-profile',
               'main' if shared else 'main10', '--bitrate', '10000000',
               '--depth-calibration', env['DEPTH_CALIBRATION']]
    if shared:
        command += ['--tone-map', 'shared']
    else:
        command += ['--gpu-rectification-map', baseline(root).get('comparison_rectification_map') or env['GPU_RECTIFICATION_MAP']]
    result = dict(name=name, started_utc=utc(), software=software_identity(), passed=False, seconds=seconds,
                  binary_sha256=sha(binary), command=command, initial_seed=seed,
                  geometry='mirrored cam0|cam1 unrectified' if shared else 'rectified cam1|cam0',
                  ae_policy='original deployed' if original else 'candidate highlight protection')
    write_json(out / 'manifest.json', result)
    child = None
    try:
        if camera_owners():
            raise RuntimeError('Unexpected camera owner before finite phase')
        SYNC.write_text('stop\n')
        SYNC.write_text('start\n')
        trace_directory = out / 'capture-traces'
        trace_directory.mkdir()
        child_environment = dict(os.environ, SC132GS_CAPTURE_TRACE_DIR=str(trace_directory))
        with (out / 'server.log').open('w') as log:
            child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=child_environment)
            record_child(root, child, binary)
            deadline = time.monotonic() + 75
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    raise RuntimeError('Test server startup exited: ' + str(child.returncode))
                if 'input_fps=' in read(out / 'server.log'):
                    break
                time.sleep(.2)
            else:
                raise RuntimeError('Test server startup timed out')
            initial = dict(seed, mode='auto')
            configure(initial, target=30)
            start = time.monotonic()
            write_json(root / 'current-phase.json', dict(phase=name, state='ready', time_utc=utc(),
                       pid=child.pid, output=str(out), expected_seconds=seconds))
            print('TEST_READY', name, child.pid, flush=True)
            steps = set()
            with (out / 'samples.jsonl').open('w') as samples:
                while time.monotonic() - start < seconds:
                    elapsed = time.monotonic() - start
                    if child.poll() is not None:
                        raise RuntimeError('Test server exited during phase')
                    if elapsed >= 25 and 25 not in steps:
                        ctl('set-brightness 40')
                        steps.add(25)
                    if elapsed >= 45 and 45 not in steps:
                        ctl('set-brightness 30')
                        steps.add(45)
                    sync = sync_state()
                    status = ctl()
                    samples.write(json.dumps(dict(elapsed_s=elapsed, time_utc=utc(), sync=sync, ae=status)) + '\n')
                    samples.flush()
                    if not healthy_sync(sync):
                        raise RuntimeError('Kernel FSYNC upstream failure: ' + sync['raw'])
                    if status.get('error_errno', status.get('control_error', status.get('error', '0'))) != '0':
                        raise RuntimeError('AE control failure: ' + str(status))
                    time.sleep(.5)
            result['final_ae'] = ctl()
            result['final_sync'] = sync_state()
            exit_code = stop_child(child, root)
            child = None
            if exit_code != 0:
                raise RuntimeError('Unclean server shutdown: ' + str(exit_code))
        log = read(out / 'server.log')
        if 'depth_disabled' in log:
            raise RuntimeError('Depth disabled during phase')
        if shared and ('shared_tone bits=8' not in log or 'depth_mono8' not in log):
            raise RuntimeError('Required shared8/depth telemetry absent')
        result['passed'] = True
    except Exception as error:
        result['error'] = str(error)
    finally:
        if child is not None:
            result['exit_code'] = stop_child(child, root)
        result['evidence_errors'] = evidence(out, 'after')
        SYNC.write_text('stop\n')
        result['completed_utc'] = utc()
        write_json(out / 'result.json', result)
        write_json(root / 'current-phase.json', dict(phase=name, state='waiting', time_utc=utc(), passed=result['passed']))
    return result


def raw_capture(root):
    probe = root / 'build/raw-sync-probe'
    if not probe.exists():
        probe = RAW_PROBE
    out = root / 'raw-capture'
    result = dict(started_utc=utc(), passed=False, probe=str(probe),
                  exposure_association_validated=False,
                  note='No AE actor is running; inherited sensor state is not a validated per-frame exposure.')
    child = None
    try:
        if camera_owners():
            raise RuntimeError('Unexpected camera owner before raw probe')
        SYNC.write_text('stop\n')
        SYNC.write_text('start\n')
        command = ['taskset', '--cpu-list', '1-6', str(probe), '/dev/video0', '/dev/video3', str(out), '5']
        result['command'] = command
        with (root / 'raw-capture.log').open('w') as log:
            child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            record_child(root, child, probe)
            deadline = time.monotonic() + 45
            observations = []
            while child.poll() is None:
                observations.append(dict(time_utc=utc(), sync=sync_state()))
                if time.monotonic() >= deadline:
                    raise RuntimeError('Raw probe exceeded deadline')
                time.sleep(.25)
            code = child.returncode
            write_json(root / 'raw-capture-sync.json', observations)
            stop_child(child, root)
            child = None
        result.update(exit_code=code, sync=sync_state())
        # STREAMOFF may intentionally clear running/locked_mask. Require an
        # observed healthy running interval and actual captured pair evidence.
        pair_files = [out / 'pair-eye0.raw10', out / 'pair-eye1.raw10', out / 'pair-timestamp.txt']
        pair_ok = all(p.is_file() and p.stat().st_size > 0 for p in pair_files)
        if code or not any(healthy_sync(x['sync']) for x in observations) or not pair_ok:
            raise RuntimeError('Raw capture command or FSYNC failed')
        result['pair_files_sha256'] = {p.name: sha(p) for p in pair_files}
        result['passed'] = True
    except Exception as error:
        result['error'] = str(error)
    finally:
        if child:
            stop_child(child, root)
        SYNC.write_text('stop\n')
        result['completed_utc'] = utc()
        write_json(root / 'raw-capture-result.json', result)
    return result


def wait_for_collector(root, name, timeout_s=120):
    acknowledgement = root / (name + '.collector-done.json')
    started = time.monotonic()
    result = dict(passed=False, phase=name, acknowledgement=str(acknowledgement),
                  started_utc=utc(), timeout_s=timeout_s)
    while time.monotonic() - started < timeout_s:
        try:
            payload = json.loads(acknowledgement.read_text())
            if isinstance(payload, dict) and payload.get('phase') == name:
                result.update(passed=True, completed_utc=utc(),
                              elapsed_s=time.monotonic() - started, acknowledgement_data=payload)
                return result
            result['last_invalid_acknowledgement'] = 'phase does not match ' + name
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as error:
            result['last_invalid_acknowledgement'] = str(error)
        time.sleep(.25)
    result.update(timed_out=True, completed_utc=utc(), elapsed_s=time.monotonic() - started)
    return result


def suite(root, seconds, include_raw, pc_handshake=False, phase_names=('old_main10', 'candidate_main10', 'shared8'), camera_cpus='1-6'):
    seed = saved_seed(root)
    if not seed:
        raise RuntimeError('Run recover first to obtain actual live AE state')
    result = dict(started_utc=utc(), passed=False, phases=[], pc_handshake=pc_handshake)
    try:
        run(['systemctl', 'stop', UNIT], timeout=35)
        if camera_owners():
            raise RuntimeError('Another owner remains after stopping original service')
        for name in phase_names:
            phase_result = phase(root, name, seconds, seed, camera_cpus)
            result['phases'].append(phase_result)
            write_json(root / 'suite-result.json', result)
            if pc_handshake:
                # phase() has stopped its child and FSYNC before publishing
                # waiting. Do not start the next owner while a PC collector
                # might still be retrying the failed/finished previous phase.
                handshake = wait_for_collector(root, name)
                phase_result['collector_handshake'] = handshake
                write_json(root / name / 'result.json', phase_result)
                write_json(root / 'suite-result.json', result)
                if not handshake['passed']:
                    raise RuntimeError('PC collector acknowledgement timed out for ' + name)
            else:
                time.sleep(5)
            if not phase_result['passed'] and any(code in phase_result.get('error', '') for code in ('error=9 ', 'error=14 ')):
                raise RuntimeError('Stop comparison after FSYNC failure; preserve evidence and restore')
        if include_raw:
            write_json(root / 'current-phase.json', dict(phase='raw-capture', state='starting', time_utc=utc()))
            result['raw_capture'] = raw_capture(root)
        result['passed'] = all(p['passed'] for p in result['phases']) and result.get('raw_capture', {'passed': True})['passed']
    except BaseException as error:
        result['error'] = str(error) or type(error).__name__
    finally:
        write_json(root / 'current-phase.json', dict(phase='restore', state='starting', time_utc=utc()))
        try:
            result['restoration'] = restore(root)
        except BaseException as error:
            result.update(passed=False, restoration_error=str(error))
        result['completed_utc'] = utc()
        write_json(root / 'suite-result.json', result)
        write_json(root / 'current-phase.json', dict(phase='complete', state='finished', time_utc=utc(), passed=result['passed']))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['backup', 'recover', 'suite', 'restore', 'status'])
    parser.add_argument('root', type=Path)
    parser.add_argument('--seconds', type=int, default=75)
    parser.add_argument('--raw', action='store_true')
    parser.add_argument('--camera-cpus', default='1-6')
    parser.add_argument('--phases', nargs='+', choices=['old_main10', 'candidate_main10', 'shared8'],
                        default=['old_main10', 'candidate_main10', 'shared8'])
    parser.add_argument('--pc-handshake', action='store_true',
                        help='Wait up to 120 seconds for a matching phase collector acknowledgement')
    args = parser.parse_args()
    if not re.fullmatch(r'[0-6](?:-[0-6])?(?:,[0-6](?:-[0-6])?)*', args.camera_cpus):
        parser.error('Camera affinity must exclude the FSYNC producer CPU 7')
    root = args.root.resolve(strict=True)
    if args.seconds < 60:
        parser.error('--seconds must be at least 60 for the specified target steps')
    if args.action != 'status' and os.geteuid() != 0:
        parser.error('Board operations require root')
    def interrupted(signum, _frame):
        raise KeyboardInterrupt('signal ' + str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    if args.action == 'backup':
        result = backup(root)
    elif args.action == 'recover':
        result = recover(root)
    elif args.action == 'suite':
        result = suite(root, args.seconds, args.raw, args.pc_handshake, args.phases, args.camera_cpus)
    elif args.action == 'restore':
        result = restore(root, external=True)
    else:
        result = dict(time_utc=utc(), unit=unit_state(), ae=try_ctl(), sync=sync_state(),
                      current_phase=read(root / 'current-phase.json'), owners=camera_owners())
    print(json.dumps(result, indent=2), flush=True)
    return 1 if result.get('passed') is False else 0


if __name__ == '__main__':
    sys.exit(main())
