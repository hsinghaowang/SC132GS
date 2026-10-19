"""Read-only collection of finite-test/deployment evidence from the board."""
from pathlib import Path
import base64,json,subprocess
ROOT=Path(__file__).resolve().parent/'rectification-evidence-20261016'
code='''from pathlib import Path
import base64,hashlib,json,subprocess
root=Path('/home/ubuntu/main10-rectification-20261016');files={}
for directory in ['fault-main10','fault-worker-main10','healthy-worker-main10','healthy-worker-main10-pinned','production-backup']:
    p=root/directory
    if p.exists():
        for f in p.iterdir():
            if f.is_file() and f.suffix in ['.json','.jsonl','.txt','.log']:files[str(f.relative_to(root))]=base64.b64encode(f.read_bytes()).decode()
for name in ['manifest.json','build.log','deployment.json','rollback.json','launch-script.diff','deployment-failed.log']:
    p=root/name
    if p.exists():files[name]=base64.b64encode(p.read_bytes()).decode()
binary=Path('/home/ubuntu/stereo-h265-rtsp/build-main10/stereo-h265-rtsp')
state=dict(binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),sync=Path('/sys/bus/platform/devices/acb3000.camss/fsync_control').read_text(),unit=subprocess.check_output(['systemctl','show','sc132gs-camera-rtsp.service','-p','ActiveState','-p','MainPID','-p','Environment'],text=True),assets={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'fixtures').iterdir() if p.suffix=='.map'})
files['current-board.json']=base64.b64encode(json.dumps(state,indent=2).encode()).decode()
files['current-server.log']=base64.b64encode(Path('/run/sc132gs-camera-server.log').read_bytes()).decode()
print(json.dumps(files))
'''
p=subprocess.run(['ssh','-o','BatchMode=yes','ubuntu@192.168.137.226','sudo -n taskset --cpu-list 1-6 python3 -'],input=code.encode(),capture_output=True,timeout=60)
p.check_returncode();files=json.loads(p.stdout)
for name,value in files.items():
    target=ROOT/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(base64.b64decode(value))
print('Collected',len(files),'evidence files')
summary={}
for name in ['fault-worker-main10','healthy-worker-main10','healthy-worker-main10-pinned']:
    data={};p=ROOT/name
    for file in ['passed.json','failure.json','restoration.json']:
        if (p/file).exists():data[file]=json.loads((p/file).read_text(encoding='utf-8'))
    if (p/'client.json').exists():
        client=json.loads((p/'client.json').read_text(encoding='utf-8'))
        data['client']={k:{key:value for key,value in v.items() if key!='rows'}|dict(frames=len(v['rows'])) for k,v in client.items()}
    summary[name]=data
(ROOT/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps({k:{'passed':v.get('passed.json',{}),'client':v.get('client',{})} for k,v in summary.items()},indent=2))
