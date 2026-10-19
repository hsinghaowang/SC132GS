"""Board cutover with immutable backup; invoked as root. No driver reload."""
from pathlib import Path
import hashlib,json,os,shutil,socket,subprocess,sys,time
ROOT=Path('/home/ubuntu/rtsp-demand-20261016')
UNIT='sc132gs-camera-rtsp.service'
DROP=Path('/etc/systemd/system/'+UNIT+'.d/99-on-demand.conf')
WATCH='rtsp-demand-rollback-20261016'
def run(a,check=True):
 p=subprocess.run(a,capture_output=True,text=True,timeout=40)
 if check and p.returncode:raise RuntimeError((a,p.returncode,p.stdout,p.stderr))
 return p.stdout+p.stderr
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def ctl(message='status'):
 with socket.socket(socket.AF_UNIX,socket.SOCK_SEQPACKET) as s:
  s.settimeout(4);s.connect('/run/sc132gs-ae.sock');s.sendall(message.encode());v=s.recv(8192).decode()
 assert v.startswith('ok '),v
 return dict(x.split('=',1) for x in v.split() if '=' in x)
def configure(v):
 return ctl('configure-exposure %s %s %s %s %s %s'%(int(v['mode']=='auto'),v['exposure_lines'],v['gain_index'],v['target_percent'],v['max_exposure_us'],v['max_gain_index']))
def snap(name):
 d=ROOT/name;d.mkdir(exist_ok=False)
 for k,a in {'unit':['systemctl','cat',UNIT],'show':['systemctl','show',UNIT],'ps':['ps','-eo','pid,args'],'fuser':['fuser','-v','/dev/video0','/dev/video3','/dev/video32','/dev/video33'],'dmesg':['dmesg']}.items():
  (d/(k+'.txt')).write_text(run(a,False))
 for p in ['/run/sc132gs-camera-server.log','/sys/bus/platform/devices/acb3000.camss/fsync_control','/sys/kernel/debug/sc132gs_sync/events']:
  (d/Path(p).name).write_bytes(Path(p).read_bytes())
 (d/'ae.json').write_text(json.dumps(ctl(),indent=2))
def rollback():
 if DROP.exists():
  assert sha(DROP)==json.loads((ROOT/'deployment.json').read_text())['drop_sha256']
  run(['systemctl','stop',UNIT]);DROP.unlink();run(['systemctl','daemon-reload']);run(['systemctl','start',UNIT])
  time.sleep(7);configure(json.loads((ROOT/'baseline.json').read_text())['ae'])
 run(['systemctl','stop',WATCH+'.timer'],False)
 snap('rollback-'+str(time.time_ns()))
 print('ROLLED BACK')
def deploy():
 assert not DROP.exists()
 assert '100% tests passed' in (ROOT/'build.log').read_text()
 ae=ctl();assert ae['error_errno']=='0'
 snap('before')
 files=['/home/ubuntu/stereo-h265-rtsp/run-camera-profile.sh','/home/ubuntu/stereo-h265-rtsp/run-stereo-rtsp.sh','/var/lib/sc132gs-camera/settings.yaml','/var/lib/sc132gs-camera/settings.json']
 baseline={'ae':ae,'files':{p:sha(p) for p in files}}
 (ROOT/'baseline.json').write_text(json.dumps(baseline,indent=2))
 backup=ROOT/'backup';backup.mkdir()
 for p in files:shutil.copy2(p,backup/Path(p).name)
 profile=Path(files[0]).read_text()
 profile=profile.replace('child=\n','child=\ndemand=0\n',1)
 anchor='        if grep -q "Capture ready: fps=$FPS" "$LOG"; then armed=1; break; fi'
 assert profile.count(anchor)==1
 profile=profile.replace(anchor,"        if grep -q 'capture_lifecycle phase=idle resources_released=1' \"$LOG\"; then demand=1; armed=1; break; fi\n"+anchor)
 profile=profile.replace('    sleep 1\n','    if ((demand == 0)); then sleep 1; fi\n',1).replace('    flowing=0\n','    flowing=$demand\n',1)
 (ROOT/'run-camera-profile.sh').write_text(profile)
 (ROOT/'run-demand.sh').write_text('#!/bin/bash\nset -euo pipefail\nexec '+str(ROOT/'build/stereo-h265-rtsp')+' "$@" --tone-map shared-detail --display-range limited\n')
 os.chmod(ROOT/'run-demand.sh',0o755)
 run(['bash','-n',str(ROOT/'run-camera-profile.sh')])
 content='[Service]\nExecStart=\nExecStart=/bin/bash '+str(ROOT/'run-camera-profile.sh')+'\nEnvironment="SERVER_BIN='+str(ROOT/'run-demand.sh')+'"\nEnvironment="BRIGHTNESS='+ae['target_percent']+'"\nEnvironment="SC132GS_CAPTURE_TRACE_DIR='+str(ROOT/'traces')+'"\n'
 meta={'drop_sha256':hashlib.sha256(content.encode()).hexdigest(),'binary_sha256':sha(ROOT/'build/stereo-h265-rtsp')}
 (ROOT/'deployment.json').write_text(json.dumps(meta,indent=2));(ROOT/'traces').mkdir(exist_ok=True)
 run(['systemd-run','--unit='+WATCH,'--on-active=25min','--timer-property=AccuracySec=1s','python3',str(ROOT/'demand_board.py'),'rollback'])
 try:
  run(['systemctl','stop',UNIT]);DROP.write_text(content);run(['systemctl','daemon-reload']);run(['systemctl','start',UNIT]);time.sleep(3)
  assert run(['systemctl','is-active',UNIT]).strip()=='active'
  configure(ae);snap('after')
  assert all(sha(p)==v for p,v in baseline['files'].items())
 except BaseException:
  rollback();raise
 print('DEPLOYED',json.dumps(meta))
if __name__=='__main__':globals()[sys.argv[1]]()
