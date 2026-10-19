"""Read the installed receiver module without unloading or modifying it."""
from pathlib import Path
import json
import subprocess

def run(*args): return subprocess.check_output(args,text=True)
root=Path('/home/ubuntu/sc132gs-camera-tests/integer-fps-20261007')
root.mkdir(exist_ok=True)
installed=run('modinfo','-F','filename','qcom_camss').strip()
copy=root/'camss-inspection.ko'
with copy.open('wb') as stream:
    subprocess.run(['zstd','-dc',installed],stdout=stream,check=True)
symbols=run('objdump','-t',str(copy))
names=sorted({line.split()[-1] for line in symbols.splitlines() if 'wm_done' in line and ' F ' in line})
record=dict(installed=installed,
    disk_srcversion=run('modinfo','-F','srcversion',installed).strip(),
    loaded_srcversion=Path('/sys/module/qcom_camss/srcversion').read_text().strip(),
    functions={})
print('disk srcversion='+record['disk_srcversion'])
print('loaded srcversion='+record['loaded_srcversion'])
for name in names:
    text=run('objdump','-dr','--disassemble='+name,str(copy))
    (root/(name+'.asm')).write_text(text)
    lines=text.splitlines()
    record['functions'][name]=[line.strip() for line in lines if 'ktime_get' in line]
    print(name)
    for index,line in enumerate(lines):
        if 'ktime_get' in line:
            print('\n'.join(lines[max(0,index-6):index+15]))
(root/'camss-timestamp.json').write_text(json.dumps(record,indent=2)+'\n')
