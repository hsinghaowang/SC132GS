#!/usr/bin/env python3
"""Linux-only adapter for the C++ CameraController; never reloads CAMSS."""
import argparse
import errno
import fcntl
import json
import math
import os
import pathlib
import re
import socket
import subprocess
import sys
import time
import uuid
import yaml

ROOT = pathlib.Path('/home/ubuntu/stereo-h265-rtsp')
STATE = pathlib.Path('/run/sc132gs-camera-state.json')
DURABLE = pathlib.Path('/var/lib/sc132gs-camera/settings.yaml')
LEGACY_DURABLE = DURABLE.with_suffix('.json')
READY = pathlib.Path('/run/sc132gs-camera-ready')
UNIT = 'sc132gs-camera-rtsp'
CLIENTS = ('18-0032', '16-0030')

class Failure(Exception):
    def __init__(self, code, system_error=0):
        self.code, self.system_error = code, system_error

def run(args, timeout=25):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise Failure(3, errno.ETIMEDOUT)
    if result.returncode:
        print('command failed: '+repr(args)+' '+result.stderr.strip(),file=sys.stderr)
        raise Failure(3, errno.EIO)
    return result.stdout.strip()

def active(unit):
    return subprocess.run(['systemctl','is-active','--quiet',unit], timeout=5).returncode == 0

def fields(text):
    return dict(token.split('=',1) for token in text.split() if '=' in token)

def request(command):
    with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as connection:
        connection.settimeout(3)
        connection.connect('/run/sc132gs-ae.sock')
        connection.sendall(command.encode())
        text = connection.recv(4096).decode()
    if not text.startswith('ok '):
        raise Failure(0, int(fields(text).get('errno', errno.EINVAL)))
    return fields(text)

def nodes():
    result = []
    for client in CLIENTS:
        root = pathlib.Path('/sys/bus/i2c/devices') / client
        if (root/'name').read_text().strip() != 'sc132gs':
            raise Failure(3, errno.ENODEV)
        matches = list((root/'video4linux').glob('v4l-subdev*'))
        if len(matches) != 1:
            raise Failure(3, errno.ENODEV)
        result.append('/dev/'+matches[0].name)
    return result

def control_values(node):
    text = run(['v4l2-ctl','-d',node,'--get-ctrl=wide_dynamic_range,analogue_gain'])
    return {line.split(':')[0].strip(): int(line.split(':')[1]) for line in text.splitlines()}

def saved():
    return json.loads(STATE.read_text()) if STATE.exists() else {}

def forward(linear):
    return 4.5*linear if linear < .018 else 1.099*linear**.45-.099

def inverse(encoded):
    return encoded/4.5 if encoded < .081 else ((encoded+.099)/1.099)**(1/.45)

def row_rate(binning,fps):
    return 162000//(3 if fps==1 else 2 if fps==2 else 1) if binning else 84000

def exposure_budget_rows(binning,fps,hdr=False):
    if hdr: return 1492 if fps>=30 else min(4350,1492+135000*(30-fps)*95//(30*fps*100))
    # Same deadline as the C++ controller/AE. Measured FPS must not enlarge it
    # after a dropped trigger. The full <=30 profile has non-overlapping readout.
    reserved=1350 if not binning and fps<=30 else 0
    available=row_rate(binning,fps)-reserved*fps
    return min(2560,max(8,available*95//(fps*100)))

def inspect():
    controls = [control_values(node) for node in nodes()]
    if controls[0]['wide_dynamic_range'] != controls[1]['wide_dynamic_range']:
        raise Failure(4, errno.EPROTO)
    mode = 'hdr' if controls[0]['wide_dynamic_range'] else 'linear'
    parameter = pathlib.Path('/sys/module/sc132gs/parameters/experimental_half_format')
    binning = parameter.exists() and parameter.read_text().strip() == 'Y'
    status = request('status')
    if status['camera_mode'] != mode:
        raise Failure(4, errno.EPROTO)
    history = saved()
    same = history.get('mode') == mode and history.get('binning') == int(binning)
    cadence = history['fps'] if same else (30 if mode == 'hdr' else 60)
    display_target = int(status['target_percent'])
    recorded_target = history.get('brightness',display_target)
    expected_native = recorded_target
    return dict(sensor_mode=mode, binning=int(binning),
        max_fps=history.get('max_fps',cadence) if same else cadence, fps=cadence,
        ae=int(status['mode']=='auto'), brightness=recorded_target if same and expected_native==int(status['target_percent']) else display_target,
        width=544 if binning else 1088, height=640 if binning else 1280,
        measured_fps_x10=int(status['fps_x10']), exposure_rows=int(status['exposure_lines']),
        gain_index=int(status['gain_index']), exposure_ceiling_rows=int(status['max_exposure_lines']),
        limited=int(status['brightness_limited']), control_error=int(status['error_errno']),
        max_exposure_us=int(status.get('max_exposure_us',0)),
        max_gain_index=int(status.get('max_gain_index',0 if mode=='hdr' else 128)),
        revision=history.get('revision',0), native_target=int(status['target_percent']))

def output(state):
    print('ok '+' '.join(f'{key}={value}' for key,value in state.items()))

def stop():
    # Old binning's EXIT trap can start the legacy owner; stop it first.
    for unit in (UNIT, 'sc132gs-binning60-rtsp','sc132gs-binning120-rtsp',
                 'sc132gs-linear120-rtsp','sc132gs-hdr-rtsp'):
        subprocess.run(['systemctl','stop',unit], capture_output=True, timeout=25)
    for unit in (UNIT,'sc132gs-linear120-rtsp','sc132gs-hdr-rtsp'):
        if active(unit): raise Failure(2, errno.EBUSY)
    READY.unlink(missing_ok=True)
    # At cold boot the media links are not enabled yet. Resolve the sensor
    # graph first, then check every capture endpoint in that graph for owners.
    media = run(['/usr/local/sbin/sc132gs-discover','media'])
    topology = run(['media-ctl','-d',media,'-p'])
    for node in set(re.findall(r'device node name (/dev/video\d+)',topology)):
        owners = subprocess.run(['fuser',node], capture_output=True, timeout=5)
        if owners.returncode == 0: raise Failure(2,errno.EBUSY)

def configure_profile(config):
    parameter = pathlib.Path('/sys/module/sc132gs/parameters/experimental_half_format')
    if config['binning'] and not parameter.exists():
        raise Failure(1, errno.EOPNOTSUPP)
    if parameter.exists():
        parameter.write_text('Y' if config['binning'] else 'N')
    if config['binning']:
        pathlib.Path('/sys/module/sc132gs/parameters/experimental_fps').write_text('120')
    for node in nodes():
        run(['v4l2-ctl','-d',node,'--set-ctrl=wide_dynamic_range='+str(int(config['mode']=='hdr'))])
        # Seed the validated exposure while STREAMOFF. A previous low-FPS
        # TOTAL must not become the first exposure at a faster new cadence;
        # a stalled sensor may never reach a frame boundary for runtime updates.
        values=('hdr_total_nominal_rows='+str(config['rows'])+
                ',hdr_total_second_ratio=256,hdr_second_exposure_ticks=0'
                if config['mode']=='hdr' else 'exposure='+str(config['rows']))
        values+=',analogue_gain='+str(config['gain'])
        run(['v4l2-ctl','-d',node,'--set-ctrl='+values])
    media = run(['/usr/local/sbin/sc132gs-discover','media'])
    script = pathlib.Path('/home/ubuntu/sc132gs-sync/configure-sc132gs-dual-pipeline.sh')
    if config['binning']:
        half = pathlib.Path('/run/sc132gs-camera-configure-half.sh')
        half.write_text(script.read_text().replace('1088x1280','544x640').replace('width=1088,height=1280','width=544,height=640'))
        script = half
    env = os.environ.copy(); env['MEDIA'] = media
    result = subprocess.run(['/bin/bash',str(script)], env=env, capture_output=True, text=True, timeout=25)
    if result.returncode:
        print('pipeline configuration failed: '+result.stderr.strip(),file=sys.stderr)
        raise Failure(3, errno.EIO)

def start(config):
    token = str(uuid.uuid4())
    subprocess.run(['systemctl','reset-failed',UNIT], capture_output=True, timeout=5)
    run(['systemd-run','--unit='+UNIT,'--property=TimeoutStopSec=15',
         '--setenv=BINNING='+str(config['binning']), '--setenv=FPS='+str(config['fps']),
         '--setenv=SENSOR_MODE='+config['mode'],
         '--setenv=TOKEN='+token, '/bin/bash', str(ROOT/'run-camera-profile.sh')])
    deadline = time.monotonic()+15
    while time.monotonic() < deadline:
        if READY.exists() and READY.read_text().strip() == token: return
        if not active(UNIT): raise Failure(3, errno.EIO)
        time.sleep(.1)
    raise Failure(3, errno.ETIMEDOUT)

def apply_exposure(config):
    # The target is sensor luma in either mode. Player transfer curves must not
    # silently alter Linear's AE target relative to HDR (or prevent target 0).
    native = config['brightness']
    request('configure-exposure '+ ' '.join(str(value) for value in
        (config['ae'],config['rows'],config['gain'],native,config['max_exposure_us'],config['max_gain_index'])))

def verify_once(config, decoded):
    if decoded:
        output_dir = pathlib.Path('/home/ubuntu/sc132gs-camera-tests') / ('apply-'+str(uuid.uuid4()))
        output_dir.mkdir(parents=True)
        (output_dir/'request.json').write_text(json.dumps(config,indent=2))
        # Measure cadence without software decoding on the capture board.
        # Full-resolution 60-FPS decoding competes with capture/encoding and
        # can cause the very drops this verification is trying to detect.
        url='rtsp://192.168.137.226:8554/stereo'
        run(['/usr/bin/python3',str(ROOT/'verify_rtsp.py'), '--url',url,
             '--seconds','8','--expected-fps',str(config['fps']),
             '--output',str(output_dir/'encoded.json')], timeout=23)
        minimum=5
        seconds=max(8,minimum/config['fps']+4)
        run(['/usr/bin/python3',str(ROOT/'verify_decode_rate.py'),
            url,'--decoder','software','--seconds',str(seconds),'--stop-after-minimum',
            '--minimum-frames',str(minimum),'--output',str(output_dir)], timeout=seconds+15)
        proof = json.loads((output_dir/'decode.json').read_text())
        width, height = (544,640) if config['binning'] else (1088,1280)
        if (proof['width'], proof['height']) != (2*width,height) or not proof['snapshot_has_spatial_detail']:
            raise Failure(4, errno.EPROTO)
    status = request('status')
    if int(status['error_errno']) or int(status['mode']=='auto') != config['ae']:
        raise Failure(4, errno.EIO)
    # Read both controls independently, including the mode-specific unit.
    exposure = 'hdr_total_nominal_rows' if config['mode']=='hdr' else 'exposure'
    readings = []
    for node in nodes():
        text = run(['v4l2-ctl','-d',node,'--get-ctrl='+exposure+',analogue_gain'])
        readings.append(tuple(int(line.split(':')[1]) for line in text.splitlines()))
    # AE can advance between separate reads; strict equality is manual-only.
    if not config['ae'] and (readings[0] != readings[1] or readings[0] != (config['rows'],config['gain'])):
        raise Failure(4, errno.EPROTO)

def verify(config, decoded):
    # The first RTSP session after an encoder restart can race media prepare.
    # Retry the decoder against the same owner; never rebuild a working graph.
    for attempt in range(3 if decoded else 1):
        try:
            verify_once(config,decoded)
            return
        except Failure:
            log=pathlib.Path('/run/sc132gs-camera-server.log')
            if log.exists():
                failure_dir=pathlib.Path('/home/ubuntu/sc132gs-camera-tests')/('failure-'+str(uuid.uuid4()))
                failure_dir.mkdir()
                (failure_dir/'server.log').write_text(log.read_text())
                (failure_dir/'request.json').write_text(json.dumps(config,indent=2))
            if not decoded or attempt==2 or not active(UNIT): raise
            time.sleep(1)

class ConfigurationLoader(yaml.SafeLoader):
    """Reject duplicate keys rather than silently overriding a setting."""
    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node,value_node in node.value:
            key=self.construct_object(key_node,deep=deep)
            if not isinstance(key,str) or key in result:
                raise Failure(0,errno.EINVAL)
            result[key]=self.construct_object(value_node,deep=deep)
        return result

def load_durable(path):
    try:
        record=yaml.load(path.read_text(),Loader=ConfigurationLoader)
    except yaml.YAMLError:
        raise Failure(0,errno.EINVAL)
    if not isinstance(record,dict): raise Failure(0,errno.EINVAL)
    # YAML users can write true/false; internal control protocol uses 0/1.
    for key in ('binning','ae'):
        if type(record.get(key)) is bool: record[key]=int(record[key])
    validate_record(record)
    return record

def durable_record():
    if DURABLE.exists(): return load_durable(DURABLE)
    # Migrate once; keep the original JSON as a recovery backup.
    record=load_durable(LEGACY_DURABLE)
    atomic_record(DURABLE,record)
    return record

def atomic_record(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    with open(temporary, 'w') as stream:
        os.chmod(temporary, 0o600)
        if path.suffix in ('.yaml','.yml'):
            document=dict(record)
            for key in ('binning','ae'): document[key]=bool(document[key])
            stream.write('# SC132GS camera settings; exposure rows are mode-specific.\n')
            stream.write('# AE on: rows/gain are startup seeds; AE adjusts them after start.\n')
            yaml.safe_dump(document,stream,sort_keys=False,default_flow_style=False)
        else: json.dump(record, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(directory)
    finally: os.close(directory)

def persist(config, revision):
    record = dict(config, revision=revision, schema=1)
    atomic_record(DURABLE, record)
    atomic_record(STATE, record)

def configuration_from_state(state):
    return dict(mode=state['sensor_mode'],binning=state['binning'],max_fps=state['max_fps'],
        fps=state['fps'],ae=state['ae'],brightness=state['brightness'],rows=state['exposure_rows'],
        gain=state['gain_index'],max_exposure_us=state['max_exposure_us'],max_gain_index=state['max_gain_index'])

def validate_record(record):
    keys = ('binning','max_fps','fps','ae','brightness','rows','gain','max_exposure_us','max_gain_index','revision')
    expected=set(keys)|{'schema','mode'}
    if (set(record)!=expected or type(record.get('schema')) is not int or
        record.get('schema') != 1 or record.get('mode') not in ('linear','hdr')):
        raise Failure(0,errno.EINVAL)
    if any(type(record.get(key)) is not int for key in keys): raise Failure(0,errno.EINVAL)
    hdr = record['mode']=='hdr'
    rates = range(1,31 if hdr else 61)
    supported = [rate for rate in rates if rate<=record['max_fps']]
    if (record['binning'] not in (0,1) or record['ae'] not in (0,1) or
        (hdr and record['binning']) or not supported or record['fps']!=max(supported) or
        not 0<=record['brightness']<=100 or not 0<=record['max_exposure_us']<=40000 or
        not 0<=record['gain']<=record['max_gain_index']<=128 or
        (hdr and record['max_exposure_us']) or record['revision']<0):
        raise Failure(0,errno.ERANGE)
    rate = row_rate(record['binning'],record['fps'])
    cap = exposure_budget_rows(record['binning'],record['fps'],hdr)
    if record['max_exposure_us']: cap=min(cap,record['max_exposure_us']*rate//1000000)
    if record['ae'] and record['rows']>cap: record['rows']=cap
    if not 8<=record['rows']<=cap: raise Failure(0,errno.ERANGE)

def restore():
    record = durable_record()
    # Disk installation supplies the tested driver to initial auto-probing.
    # Never unload either module or rebuild an already registered media graph.
    run(['modprobe','sc132gs'])
    run(['modprobe','qcom_camss'])
    deadline=time.monotonic()+30
    while True:
        try: nodes(); break
        except (Failure,OSError):
            if time.monotonic()>=deadline: raise Failure(3,errno.ENODEV)
            time.sleep(.5)
    stop()
    try:
        configure_profile(record); start(record)
        apply_exposure(record); verify(record,True)
        # Restoring does not rewrite flash or change the saved revision.
        atomic_record(STATE,record)
        output(inspect())
    except Exception:
        stop()
        raise

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action',choices=('status','apply','save','restore'))
    for name in ('binning','max-fps','fps','ae','brightness','exposure-us','hdr-total-rows',
                 'gain-index','max-exposure-us','max-gain-index','revision'):
        parser.add_argument('--'+name,type=int)
    parser.add_argument('--mode',choices=('linear','hdr'))
    args = parser.parse_args()
    if os.geteuid() != 0: raise Failure(3, errno.EPERM)
    if args.action == 'status': output(inspect()); return
    with open('/run/sc132gs-camera.lock','a') as lock, open('/run/sc132gs-mode.lock','a') as legacy_lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            fcntl.flock(legacy_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise Failure(2, errno.EBUSY)
        if args.action == 'restore': restore(); return
        prior = inspect()
        if args.action == 'save':
            persist(configuration_from_state(prior),prior['revision'])
            output(prior); return
        if prior['revision'] != args.revision: raise Failure(2, errno.ESTALE)
        if args.mode == 'hdr' and args.binning: raise Failure(1, errno.EOPNOTSUPP)
        if args.fps not in range(1,31 if args.mode=='hdr' else 61): raise Failure(1, errno.EOPNOTSUPP)
        same_geometry = prior['sensor_mode']==args.mode and prior['binning']==args.binning
        restart = not same_geometry or prior['fps'] != args.fps
        rate = row_rate(args.binning,args.fps)
        cap = exposure_budget_rows(args.binning,args.fps,args.mode=='hdr')
        if args.max_exposure_us and args.mode=='linear': cap = min(cap,args.max_exposure_us*rate//1000000)
        if args.exposure_us >= 0: rows = round(args.exposure_us*rate/1000000)
        elif args.hdr_total_rows >= 0: rows = args.hdr_total_rows
        elif args.mode=='linear' and prior['sensor_mode']=='linear':
            old_rate = row_rate(prior['binning'],prior['fps'])
            rows = round(prior['exposure_rows']*rate/old_rate)
        elif same_geometry: rows = prior['exposure_rows']
        else: rows = 1492 if args.mode=='hdr' else round(.008*rate)
        if args.ae: rows = max(8,min(rows,cap))
        if rows < 8 or rows > cap: raise Failure(0,errno.ERANGE)
        gain = args.gain_index if args.gain_index >= 0 else (prior['gain_index'] if same_geometry else 0)
        gain = min(gain,args.max_gain_index)
        desired = dict(mode=args.mode,binning=args.binning,max_fps=args.max_fps,fps=args.fps,
            ae=args.ae,brightness=args.brightness,rows=rows,gain=gain,
            max_exposure_us=args.max_exposure_us,max_gain_index=args.max_gain_index)
        previous = dict(mode=prior['sensor_mode'],binning=prior['binning'],max_fps=prior['max_fps'],
            fps=prior['fps'],ae=prior['ae'],brightness=prior['brightness'],rows=prior['exposure_rows'],
            gain=prior['gain_index'],max_exposure_us=prior['max_exposure_us'],max_gain_index=prior['max_gain_index'])
        changed = False
        try:
            if restart:
                # Do not stop the existing service if required driver features are absent.
                if args.binning and not pathlib.Path('/sys/module/sc132gs/parameters/experimental_half_format').exists():
                    raise Failure(1,errno.EOPNOTSUPP)
                changed = True
                stop(); configure_profile(desired); start(desired)
            else: changed = True
            apply_exposure(desired)
            verify(desired,restart)
            persist(desired,prior['revision']+1)
            output(inspect())
        except Exception as error:
            failed = False
            if changed:
                try:
                    if restart: stop(); configure_profile(previous); start(previous)
                    apply_exposure(previous); verify(previous,restart)
                    persist(previous,prior['revision'])
                except Exception: failed = True
            code = error.code if isinstance(error,Failure) else 3
            system_error = error.system_error if isinstance(error,Failure) else getattr(error,'errno',errno.EIO)
            print(f'error={code} errno={system_error or errno.EIO} rollback_failed={int(failed)}')
            raise SystemExit(1)

if __name__ == '__main__':
    try: main()
    except Failure as error:
        print(f'error={error.code} errno={error.system_error} rollback_failed=0')
        sys.exit(1)
    except Exception as error:
        print(f'error=3 errno={getattr(error,"errno",errno.EIO) or errno.EIO} rollback_failed=0')
        sys.exit(1)
