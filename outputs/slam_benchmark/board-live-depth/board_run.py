"""Finite exclusive camera experiment, always restoring the previous owner."""
from pathlib import Path
import hashlib,json,os,shlex,shutil,socket,struct,subprocess,sys,threading,time

ROOT=Path('/home/ubuntu/board-live-depth-20261015')
UNIT='sc132gs-camera-rtsp.service'
CONTROL=Path('/sys/bus/platform/devices/acb3000.camss/fsync_control')
name=sys.argv[1];seconds=int(sys.argv[2]);out=ROOT/name;out.mkdir(exist_ok=False)
def run(args):return subprocess.check_output(args,text=True,stderr=subprocess.STDOUT)
def hashes():
    names=['/var/lib/sc132gs-camera/settings.json','/var/lib/sc132gs-camera/settings.yaml','/home/ubuntu/stereo-h265-rtsp/run-camera-profile.sh','/home/ubuntu/stereo-h265-rtsp/run-stereo-rtsp.sh','/home/ubuntu/stereo-h265-rtsp/build-main10/stereo-h265-rtsp']
    return {n:hashlib.sha256(Path(n).read_bytes()).hexdigest() for n in names}
assert run(['systemctl','is-active',UNIT]).strip()=='active'
environment=shlex.split(run(['systemctl','show',UNIT,'--property=Environment','--value']))
assert {'BINNING=0','FPS=30','SENSOR_MODE=linear'}.issubset(environment)
(out/'original-unit.txt').write_text(run(['systemctl','cat',UNIT]))
(out/'original-environment.json').write_text(json.dumps(environment))
before=hashes();(out/'hashes-before.json').write_text(json.dumps(before,indent=2))
(out/'sync-before.txt').write_text(CONTROL.read_text())
(out/'dmesg-before.txt').write_text(run(['dmesg']))
shutil.copyfile('/run/sc132gs-camera-server.log',out/'original-server.log')
for file in ROOT.iterdir():
    if file.suffix in ['.i32','.u8','.txt','.json'] and file.is_file():shutil.copyfile(file,out/file.name)
stop=threading.Event()
def echo():
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as s:
        s.bind(('0.0.0.0',8767));s.settimeout(.25)
        while not stop.is_set():
            try:
                payload,address=s.recvfrom(128);stamp=time.monotonic_ns()
                s.sendto(payload[:8]+struct.pack('<Q',stamp),address)
            except socket.timeout:pass
def monitor():
    with (out/'sync-monitor.jsonl').open('w') as file:
        while not stop.is_set():
            file.write(json.dumps(dict(monotonic_ns=time.monotonic_ns(),state=CONTROL.read_text().strip()))+'\n');file.flush()
            stop.wait(.2)
thread=threading.Thread(target=echo);observer=threading.Thread(target=monitor);child=None;code=-1
try:
    run(['systemctl','stop',UNIT]);CONTROL.write_text('stop\n');CONTROL.write_text('start\n')
    thread.start()
    observer.start()
    with (out/'live.log').open('w') as log:
        child=subprocess.Popen(['taskset','--cpu-list','4-6',str(ROOT/'board-live-depth'),str(seconds)],cwd=out,stdout=log,stderr=subprocess.STDOUT)
        (out/'pid').write_text(str(child.pid));print('TEST_STARTED',name,child.pid,flush=True)
        code=child.wait(timeout=seconds+100)
        (out/'sync-after-test.txt').write_text(CONTROL.read_text())
finally:
    if child and child.poll() is None:
        child.terminate()
        try:child.wait(timeout=15)
        except subprocess.TimeoutExpired:child.kill();child.wait()
    stop.set()
    if thread.is_alive():thread.join()
    if observer.is_alive():observer.join()
    CONTROL.write_text('stop\n')
    restore=subprocess.run(['systemctl','start',UNIT],capture_output=True,text=True)
    if restore.returncode:
        run(['systemd-run','--unit='+UNIT,'--property=TimeoutStopSec=15s']+['--setenv='+e for e in environment]+['/bin/bash','/home/ubuntu/stereo-h265-rtsp/run-camera-profile.sh'])
    for _ in range(150):
        if 'running=1' in CONTROL.read_text() and 'Capture ready:' in Path('/run/sc132gs-camera-server.log').read_text():break
        time.sleep(.1)
    after=hashes()
    (out/'hashes-after.json').write_text(json.dumps(after,indent=2))
    (out/'sync-final.txt').write_text(CONTROL.read_text())
    (out/'dmesg-after.txt').write_text(run(['dmesg']))
    restored=run(['systemctl','is-active',UNIT]).strip()=='active' and before==after and 'running=1' in CONTROL.read_text()
    (out/'restoration.json').write_text(json.dumps(dict(child_exit=code,profile_hashes_unchanged=before==after,original_active=restored),indent=2))
    print('RESTORED',restored,'TEST_EXIT',code,flush=True)
    assert restored
raise SystemExit(code)
