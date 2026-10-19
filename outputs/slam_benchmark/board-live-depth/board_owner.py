"""Reversible live owner. Stop or failure restores the saved camera service."""
from pathlib import Path
import datetime,hashlib,json,shlex,shutil,signal,subprocess,time
ROOT=Path('/home/ubuntu/board-live-depth-20261015')
UNIT='sc132gs-camera-rtsp.service'
CONTROL=Path('/sys/bus/platform/devices/acb3000.camss/fsync_control')
def run(args):return subprocess.check_output(args,text=True,stderr=subprocess.STDOUT)
def hashes():
    paths=['/var/lib/sc132gs-camera/settings.json','/var/lib/sc132gs-camera/settings.yaml','/home/ubuntu/stereo-h265-rtsp/run-camera-profile.sh','/home/ubuntu/stereo-h265-rtsp/run-stereo-rtsp.sh','/home/ubuntu/stereo-h265-rtsp/build-main10/stereo-h265-rtsp']
    return {p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths}
assert run(['systemctl','is-active',UNIT]).strip()=='active','Original owner must be active'
environment=shlex.split(run(['systemctl','show',UNIT,'--property=Environment','--value']))
assert {'BINNING=0','FPS=30','SENSOR_MODE=linear'}.issubset(environment)
out=ROOT/('running-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir()
before=hashes();(out/'preservation-before.json').write_text(json.dumps(dict(environment=environment,hashes=before),indent=2))
(out/'original-unit.txt').write_text(run(['systemctl','cat',UNIT]))
shutil.copyfile('/run/sc132gs-camera-server.log',out/'original-server.log')
for path in ROOT.iterdir():
    if path.is_file() and path.suffix in ['.i32','.u8','.txt','.json']:shutil.copyfile(path,out/path.name)
(ROOT/'active-run.txt').write_text(str(out)+'\n')
child=None;stopping=False;code=-1
def request_stop(*_):
    global stopping
    stopping=True
    if child and child.poll() is None:child.terminate()
signal.signal(signal.SIGTERM,request_stop);signal.signal(signal.SIGINT,request_stop)
try:
    run(['systemctl','stop',UNIT]);CONTROL.write_text('stop\n');CONTROL.write_text('start\n')
    with (out/'live.log').open('w') as log:
        child=subprocess.Popen(['taskset','--cpu-list','4-6',str(ROOT/'board-live-depth'),'0'],cwd=out,stdout=log,stderr=subprocess.STDOUT)
        print('LIVE_OWNER',child.pid,out,flush=True)
        while child.poll() is None:
            if stopping:child.terminate()
            (out/'sync-current.txt').write_text(CONTROL.read_text())
            time.sleep(.5)
        code=child.returncode
        (out/'sync-after-test.txt').write_text(CONTROL.read_text())
finally:
    if child and child.poll() is None:
        child.terminate()
        try:child.wait(timeout=15)
        except subprocess.TimeoutExpired:child.kill();child.wait()
    CONTROL.write_text('stop\n')
    restore=subprocess.run(['systemctl','start',UNIT],capture_output=True,text=True)
    if restore.returncode:run(['systemd-run','--unit='+UNIT,'--property=TimeoutStopSec=15s']+['--setenv='+e for e in environment]+['/bin/bash','/home/ubuntu/stereo-h265-rtsp/run-camera-profile.sh'])
    for _ in range(150):
        if 'running=1' in CONTROL.read_text() and 'Capture ready:' in Path('/run/sc132gs-camera-server.log').read_text():break
        time.sleep(.1)
    after=hashes();restored=before==after and run(['systemctl','is-active',UNIT]).strip()=='active' and 'running=1' in CONTROL.read_text()
    (out/'restoration.json').write_text(json.dumps(dict(original_active=restored,profile_hashes_unchanged=before==after,child_exit=code,requested_stop=stopping),indent=2))
    print('ORIGINAL_RESTORED',restored,flush=True)
    assert restored
raise SystemExit(0 if stopping else (code or 1))
