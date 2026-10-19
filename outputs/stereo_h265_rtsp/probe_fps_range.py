#!/usr/bin/env python3
"""Sequential real camera transactions; no kernel reload or synthetic frames."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import camera_platform as platform

parser=argparse.ArgumentParser()
parser.add_argument('profile',choices=('full','binning','hdr','ae'))
parser.add_argument('--rates',type=int,nargs='+')
args=parser.parse_args()
root=Path('/home/ubuntu/sc132gs-camera-tests/integer-fps-20261007')
root.mkdir(parents=True,exist_ok=True)
transaction_path=root/(args.profile+'-transactions.json')
records=json.loads(transaction_path.read_text()) if transaction_path.exists() else []
def apply(label,options,expected_fps=None,accepted=True):
    before=platform.inspect()
    artifacts=set(root.parent.glob('apply-*'))
    result=subprocess.run(['/usr/local/bin/sc132gs-camera','apply']+options,
        capture_output=True,text=True,timeout=90)
    after=platform.inspect()
    record=dict(label=label,options=options,returncode=result.returncode,
        stdout=result.stdout,stderr=result.stderr,before=before,after=after)
    records.append(record)
    transaction_path.write_text(json.dumps(records,indent=2))
    print(label+' '+result.stdout.strip()+' '+result.stderr.strip(),flush=True)
    assert (result.returncode==0)==accepted,record
    if accepted:
        assert after['control_error']==0
        if expected_fps:
            assert after['fps']==expected_fps
            assert abs(after['measured_fps_x10']/10-expected_fps)<max(.2,expected_fps*.03),after
        for artifact in sorted(set(root.parent.glob('apply-*'))-artifacts,key=lambda p:p.stat().st_mtime):
            shutil.copytree(artifact,root/label,dirs_exist_ok=True)
    else:
        for key in ('sensor_mode','binning','fps','revision','ae','brightness'):
            assert before[key]==after[key],(key,before,after)
    return after

if args.profile in ('full','binning','hdr'):
    mode='hdr' if args.profile=='hdr' else 'linear'
    binning='on' if args.profile=='binning' else 'off'
    rates=args.rates or {'full':(1,2,15,24,31,48,59,60),'binning':(1,2,3,24,47,60),'hdr':(1,24,30)}[args.profile]
    for fps in rates:
        state=apply(args.profile+'-'+str(fps),['--mode',mode,'--binning',binning,
            '--max-fps',str(fps),'--ae','on','--max-exposure-us','0'],fps)
        expected_cap=1492 if mode=='hdr' else min(2560,platform.row_rate(state['binning'],fps)*95//(fps*100))
        assert state['exposure_ceiling_rows']==expected_cap,state
else:
    apply('ae-base24',['--mode','linear','--binning','off','--max-fps','24','--ae','on','--max-exposure-us','0'],24)
    state=apply('manual28ms',['--ae','off','--exposure-us','28000','--gain-index','0'],24)
    assert state['exposure_rows']==2352 and state['exposure_ceiling_rows']==2560,state
    apply('manual-too-long-at60',['--max-fps','60'],accepted=False)
    state=apply('ae-clamp-at60',['--max-fps','60','--ae','on'],60)
    assert state['exposure_rows']<=1330 and state['exposure_ceiling_rows']==1330,state
    state=apply('ae-user-cap8ms',['--max-fps','24','--max-exposure-us','8000'],24)
    assert state['exposure_ceiling_rows']==672 and state['exposure_rows']<=672,state
    state=apply('ae-release-cap',['--max-exposure-us','0'],24)
    assert state['exposure_ceiling_rows']==2560,state
print('profile '+args.profile+' passed',flush=True)
