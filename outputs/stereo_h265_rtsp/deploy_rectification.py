"""Board-only reversible cutover of the existing camera owner (run as root)."""
from pathlib import Path
import difflib,hashlib,json,os,shlex,shutil,socket,subprocess,sys,time

ROOT=Path('/home/ubuntu/main10-rectification-20261016')
BACKUP=ROOT/'production-backup'
UNIT='sc132gs-camera-rtsp.service'
BINARY=Path('/home/ubuntu/stereo-h265-rtsp/build-main10/stereo-h265-rtsp')
SCRIPT=Path('/home/ubuntu/stereo-h265-rtsp/run-stereo-rtsp.sh')
DROPIN=Path('/etc/systemd/system/sc132gs-camera-rtsp.service.d/40-gpu-rectification.conf')
CONTROL=Path('/sys/bus/platform/devices/acb3000.camss/fsync_control')
PROFILE_FILES=[Path('/var/lib/sc132gs-camera/settings.json'),Path('/var/lib/sc132gs-camera/settings.yaml'),Path('/home/ubuntu/stereo-h265-rtsp/run-camera-profile.sh')]

def run(args):return subprocess.check_output(args,text=True,stderr=subprocess.STDOUT)
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def ctl(message):
    with socket.socket(socket.AF_UNIX,socket.SOCK_SEQPACKET) as s:
        s.settimeout(3);s.connect('/run/sc132gs-ae.sock');s.sendall(message.encode());reply=s.recv(8192).decode()
    if not reply.startswith('ok '):raise RuntimeError(reply)
    return dict(item.split('=',1) for item in reply.split() if '=' in item)
def configure(s):
    ctl('configure-exposure %s %s %s %s %s %s'%(int(s['mode']=='auto'),s['exposure_lines'],s['gain_index'],s['target_percent'],s['max_exposure_us'],s['max_gain_index']))
def check_owner():
    processes=run(['ps','-eo','args'])
    assert not any('stability_monitor.py' in s and 'python' in s for s in processes.splitlines()),'another camera test owns the devices'
    assert not any('test_rectification_board.py' in s and 'python' in s for s in processes.splitlines()),'finite test still running'
def atomic_copy(source,target):
    previous=target.stat() if target.exists() else source.stat()
    temp=target.with_name(target.name+'.rectification-new');shutil.copy2(source,temp)
    os.chown(temp,previous.st_uid,previous.st_gid);os.chmod(temp,previous.st_mode & 0o7777);os.replace(temp,target)
def start(state):
    p=subprocess.run(['systemctl','start',UNIT],capture_output=True,text=True)
    if p.returncode:run(['systemd-run','--unit='+UNIT,'--property=TimeoutStopSec=20s']+['--setenv='+e for e in state['environment']]+['/bin/bash','/home/ubuntu/stereo-h265-rtsp/run-camera-profile.sh'])
    for _ in range(240):
        try:
            sync=CONTROL.read_text()
            if 'running=1' in sync and 'error=0 ' in sync and 'Capture ready:' in Path('/run/sc132gs-camera-server.log').read_text():
                configure(state['ae']);return
        except (OSError,RuntimeError):pass
        time.sleep(.1)
    raise RuntimeError('camera startup did not become ready')
def rollback():
    check_owner();state=json.loads((BACKUP/'state.json').read_text())
    subprocess.run(['systemctl','stop',UNIT],check=False)
    atomic_copy(BACKUP/'stereo-h265-rtsp',BINARY);atomic_copy(BACKUP/'run-stereo-rtsp.sh',SCRIPT)
    if state['dropin_existed']:atomic_copy(BACKUP/'40-gpu-rectification.conf',DROPIN)
    elif DROPIN.exists():DROPIN.unlink()
    run(['systemctl','daemon-reload']);start(state)
    assert digest(BINARY)==state['binary_sha256'] and digest(SCRIPT)==state['script_sha256']
    (ROOT/'rollback.json').write_text(json.dumps(dict(restored=True,ae=ctl('status'),sync=CONTROL.read_text()),indent=2))
def apply():
    check_owner();assert run(['systemctl','is-active',UNIT]).strip()=='active'
    assert digest(BINARY)=='bce3ba5017f04f27a10a791a4b66f22e49774110ea376ee40ed8a22c16b16ea8','original binary changed since staging'
    assert (ROOT/'healthy-worker-main10-pinned/passed.json').exists(),'healthy finite test must pass first'
    assert (ROOT/'fault-worker-main10/passed.json').exists(),'depth fault test must pass first'
    environment=shlex.split(run(['systemctl','show',UNIT,'--property=Environment','--value']))
    assert {'BINNING=0','FPS=30','SENSOR_MODE=linear'}.issubset(environment)
    BACKUP.mkdir(exist_ok=False)
    state=dict(environment=environment,ae=ctl('status'),binary_sha256=digest(BINARY),script_sha256=digest(SCRIPT),profile_hashes={str(p):digest(p) for p in PROFILE_FILES},dropin_existed=DROPIN.exists(),new_binary_sha256=digest(ROOT/'build/stereo-h265-rtsp'))
    shutil.copy2(BINARY,BACKUP/'stereo-h265-rtsp');shutil.copy2(SCRIPT,BACKUP/'run-stereo-rtsp.sh')
    if DROPIN.exists():shutil.copy2(DROPIN,BACKUP/'40-gpu-rectification.conf')
    (BACKUP/'state.json').write_text(json.dumps(state,indent=2))
    (BACKUP/'unit.txt').write_text(run(['systemctl','cat',UNIT]))
    (BACKUP/'server.log').write_bytes(Path('/run/sc132gs-camera-server.log').read_bytes())
    (BACKUP/'sync.txt').write_text(CONTROL.read_text());(BACKUP/'dmesg.txt').write_text(run(['dmesg']))
    text=SCRIPT.read_text();anchor='BITRATE=${BITRATE:-20000000}'
    assert text.count(anchor)==1
    text=text.replace(anchor,anchor+'''
# Private GPU adapters; no camera/AE settings are changed by these options.
GPU_OPTIONS=()
[[ -z ${GPU_RECTIFICATION_MAP:-} ]] || GPU_OPTIONS+=(--gpu-rectification-map "$GPU_RECTIFICATION_MAP")
[[ -z ${DEPTH_CALIBRATION:-} ]] || GPU_OPTIONS+=(--depth-calibration "$DEPTH_CALIBRATION")''')
    end='--auto-exposure "$AE_MODE" --hevc-profile "$HEVC_PROFILE" --bitrate "$BITRATE"'
    assert text.count(end)==2;text=text.replace(end,end+' "${GPU_OPTIONS[@]}"')
    staged=ROOT/'run-stereo-rtsp-gpu.sh';staged.write_text(text);os.chmod(staged,0o755)
    run(['bash','-n',str(staged)])
    (ROOT/'launch-script.diff').write_text(''.join(difflib.unified_diff(SCRIPT.read_text().splitlines(True),text.splitlines(True),fromfile='original',tofile='gpu')))
    try:
        run(['systemctl','stop',UNIT]);atomic_copy(ROOT/'build/stereo-h265-rtsp',BINARY);atomic_copy(staged,SCRIPT)
        DROPIN.parent.mkdir(parents=True,exist_ok=True)
        DROPIN.write_text('[Service]\nEnvironment="GPU_RECTIFICATION_MAP='+str(ROOT/'fixtures/calibration.map')+'"\nEnvironment="DEPTH_CALIBRATION='+str(ROOT/'depth-calibration')+'"\n')
        run(['systemctl','daemon-reload']);start(state)
        time.sleep(8)
        log=Path('/run/sc132gs-camera-server.log').read_text();sync=CONTROL.read_text()
        assert 'gpu_rectification active=1 order=cam1_cam0 width=2176 height=1280 bits=10' in log
        assert 'depth_pipeline' in log and 'depth_disabled' not in log
        assert 'running=1' in sync and 'error=0 ' in sync
        assert {str(p):digest(p) for p in PROFILE_FILES}==state['profile_hashes']
        (ROOT/'deployment.json').write_text(json.dumps(dict(deployed=True,binary_sha256=digest(BINARY),profile_hashes_unchanged=True,ae=ctl('status'),sync=sync,environment=run(['systemctl','show',UNIT,'--property=Environment','--value'])),indent=2))
        print('DEPLOYED',digest(BINARY),flush=True)
    except BaseException:
        (ROOT/'deployment-failed.log').write_bytes(Path('/run/sc132gs-camera-server.log').read_bytes())
        rollback();raise
if __name__=='__main__':
    if sys.argv[1]=='apply':apply()
    elif sys.argv[1]=='rollback':rollback()
    else:raise SystemExit('apply or rollback')
