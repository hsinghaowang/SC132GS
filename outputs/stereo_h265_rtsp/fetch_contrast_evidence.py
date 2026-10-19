"""Fetch a fixed allowlist; verify archive and every extracted evidence file."""
from pathlib import Path
import argparse,hashlib,json,subprocess,tarfile
p=argparse.ArgumentParser();p.add_argument('--offline',action='store_true');p.add_argument('--label');a=p.parse_args()
OUT=Path(__file__).resolve().parent/'contrast8-evidence-20261016'
ROOT='/home/ubuntu/shared8-contrast-20261016-1740';label=a.label or ('offline' if a.offline else 'board')
code=f'''from pathlib import Path
import tarfile,hashlib,json,os
os.sched_setaffinity(0,{{1,2,3}});r=Path({ROOT!r})
paths=[p for p in r.iterdir() if p.is_file() and p.suffix in ('.json','.jsonl','.txt','.log','.py','.yaml','.h265','.nv12','.sh')]
for d in r.iterdir():
 if d.name=='live-600s' and {a.offline!r}:continue
 if d.is_dir() and (d.name.startswith(('replay','before-','after-','rollback-')) or d.name in ('range-probe-initial','raw-capture','live-600s','final-accepted')):
  paths.extend(p for p in d.rglob('*') if p.is_file() and not p.is_symlink())
manifest={{p.relative_to(r).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
m=r/{(label+'-sha256.json')!r};m.write_text(json.dumps(manifest,indent=2));paths.append(m)
archive=r/{(label+'-evidence.tar.gz')!r}
with tarfile.open(archive,'w:gz',compresslevel=1) as t:
 for p in paths:t.add(p,arcname=p.relative_to(r).as_posix(),recursive=False)
print(json.dumps(dict(sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),bytes=archive.stat().st_size,files=len(paths))))
'''
x=subprocess.run(['ssh','ubuntu@192.168.137.226','sudo','-n','python3','-'],input=code,text=True,capture_output=True,check=True,timeout=120)
meta=json.loads(x.stdout);archive=OUT/(label+'-evidence.tar.gz')
subprocess.run(['scp','ubuntu@192.168.137.226:'+ROOT+'/'+archive.name,str(archive)],check=True,timeout=180)
assert hashlib.sha256(archive.read_bytes()).hexdigest()==meta['sha256']
d=OUT/label;d.mkdir(exist_ok=False)
with tarfile.open(archive) as t:t.extractall(d,filter='data')
m=json.loads((d/(label+'-sha256.json')).read_text());assert all(hashlib.sha256((d/p).read_bytes()).hexdigest()==v for p,v in m.items())
(OUT/(label+'-download.json')).write_text(json.dumps(meta,indent=2));print(json.dumps(meta))
