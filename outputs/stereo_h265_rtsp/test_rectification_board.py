"""Finite Main10/AE/isolated-depth test, preserving/restoring the existing service."""
from pathlib import Path
import hashlib,json,os,shlex,socket,subprocess,sys,time
ROOT=Path('/home/ubuntu/main10-rectification-20261016');UNIT='sc132gs-camera-rtsp.service'
CONTROL=Path('/sys/bus/platform/devices/acb3000.camss/fsync_control')
os.sched_setaffinity(0,set(range(1,7)))
out=ROOT/sys.argv[1];out.mkdir(exist_ok=False);duration=int(sys.argv[2]);inject=len(sys.argv)>3 and sys.argv[3]=='fault'
def run(args):return subprocess.check_output(args,text=True,stderr=subprocess.STDOUT)
def hashes():
    paths=['/var/lib/sc132gs-camera/settings.json','/var/lib/sc132gs-camera/settings.yaml','/home/ubuntu/stereo-h265-rtsp/build-main10/stereo-h265-rtsp','/home/ubuntu/stereo-h265-rtsp/run-camera-profile.sh','/home/ubuntu/stereo-h265-rtsp/run-stereo-rtsp.sh']
    return {p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths}
def ctl(message):
    with socket.socket(socket.AF_UNIX,socket.SOCK_SEQPACKET) as s:
        s.settimeout(3);s.connect('/run/sc132gs-ae.sock');s.sendall(message.encode());reply=s.recv(8192).decode()
    if not reply.startswith('ok '):raise RuntimeError(reply)
    return dict(item.split('=',1) for item in reply.split() if '=' in item)
def configure(s,enabled=None,target=None):
    return ctl('configure-exposure %s %s %s %s %s %s'%((int(s['mode']=='auto') if enabled is None else enabled),s['exposure_lines'],s['gain_index'],s['target_percent'] if target is None else target,s['max_exposure_us'],s['max_gain_index']))
# Never interrupt another active stability monitor or camera owner.
processes=run(['ps','-eo','args'])
if any('stability_monitor.py' in line and 'python' in line for line in processes.splitlines()):raise RuntimeError('active stability test: owner selection required')
assert run(['systemctl','is-active',UNIT]).strip()=='active'
environment=shlex.split(run(['systemctl','show',UNIT,'--property=Environment','--value']))
assert {'BINNING=0','FPS=30','SENSOR_MODE=linear'}.issubset(environment)
before=hashes();ae=ctl('status')
(out/'baseline.json').write_text(json.dumps(dict(hashes=before,ae=ae,environment=environment),indent=2))
(out/'original-unit.txt').write_text(run(['systemctl','cat',UNIT]))
(out/'original-server.log').write_bytes(Path('/run/sc132gs-camera-server.log').read_bytes())
(out/'dmesg-before.txt').write_text(run(['dmesg']))
child=None;exit_code=None
try:
    run(['systemctl','stop',UNIT]);CONTROL.write_text('stop\n');CONTROL.write_text('start\n')
    env=os.environ.copy()
    if inject:env['LD_PRELOAD']=str(ROOT/'depth-fault.so')
    command=['taskset','--cpu-list','1-6',str(ROOT/'build/stereo-h265-rtsp'),'--cam0','/dev/video0','--cam1','/dev/video3','--bind','192.168.137.226','--port','8554','--mount','/stereo','--downscale','1','--fps','30','--brightness',ae['target_percent'],'--auto-exposure','off','--hevc-profile','main10','--bitrate','10000000','--gpu-rectification-map',str(ROOT/'fixtures/calibration.map'),'--depth-calibration',str(ROOT/'depth-calibration')]
    with (out/'server.log').open('w') as log:
        child=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,env=env)
        (out/'pid').write_text(str(child.pid))
        for _ in range(150):
            if child.poll() is not None:raise RuntimeError('new server startup failed')
            if 'Capture ready:' in (out/'server.log').read_text():break
            time.sleep(.1)
        else:raise RuntimeError('startup timeout')
        configure(ae);start=time.monotonic();phase=0
        print('TEST_READY',out.name,child.pid,flush=True)
        with (out/'samples.jsonl').open('w') as samples:
            while time.monotonic()-start<duration:
                elapsed=time.monotonic()-start
                if child.poll() is not None:raise RuntimeError('new server exited')
                state=CONTROL.read_text().strip();current=ctl('status')
                samples.write(json.dumps(dict(elapsed_s=elapsed,pid=child.pid,sync=state,ae=current))+'\n');samples.flush()
                if 'error=0 ' not in state or 'running=1' not in state:raise RuntimeError('shared camera upstream error')
                if inject and elapsed>=7 and phase==0:configure(ae,enabled=1,target=ae['target_percent']);phase=1
                if inject and elapsed>=16 and phase==1:ctl('set-brightness '+str(min(70,int(ae['target_percent'])+10)));phase=2
                if inject and elapsed>=35 and phase==2:configure(ae);phase=3
                time.sleep(.5)
        child.terminate();exit_code=child.wait(timeout=25);child=None
    assert exit_code==0,'unclean shutdown'
    text=(out/'server.log').read_text()
    if inject:assert 'TEST_FAULT_INJECTED' in text and 'depth_disabled stage=2 native=-5 stereo_continues=1' in text
    else:assert 'depth_disabled' not in text
    (out/'passed.json').write_text(json.dumps(dict(passed=True,seconds=duration,fault_injection=inject),indent=2))
except BaseException as error:
    (out/'failure.json').write_text(json.dumps(dict(passed=False,error=str(error),sync=CONTROL.read_text()),indent=2));raise
finally:
    (out/'events.txt').write_text(Path('/sys/kernel/debug/sc132gs_sync/events').read_text())
    if child and child.poll() is None:
        child.terminate()
        try:child.wait(timeout=25)
        except subprocess.TimeoutExpired:child.kill();child.wait()
    (out/'sync-after-test.txt').write_text(CONTROL.read_text())
    (out/'dmesg-after.txt').write_text(run(['dmesg']))
    CONTROL.write_text('stop\n')
    p=subprocess.run(['systemctl','start',UNIT],capture_output=True,text=True)
    if p.returncode:run(['systemd-run','--unit='+UNIT,'--property=TimeoutStopSec=20s']+['--setenv='+e for e in environment]+['/bin/bash','/home/ubuntu/stereo-h265-rtsp/run-camera-profile.sh'])
    for _ in range(150):
        try:
            if 'running=1' in CONTROL.read_text():configure(ae);break
        except (OSError,RuntimeError):pass
        time.sleep(.1)
    after=hashes();state=CONTROL.read_text();restored=before==after and 'running=1' in state and 'error=0 ' in state
    (out/'restoration.json').write_text(json.dumps(dict(profile_hashes_unchanged=before==after,original_active=restored,ae=ctl('status')),indent=2))
    print('ORIGINAL_RESTORED',restored,flush=True);assert restored
