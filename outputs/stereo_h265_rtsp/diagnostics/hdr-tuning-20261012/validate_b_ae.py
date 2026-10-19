"""Exercise B-profile AE from deliberately dark and bright exposure seeds."""
import json
from pathlib import Path
import subprocess
import time

OUT=Path('/home/ubuntu/hdr-tuning-20261012')
def run(*args):
    return subprocess.check_output(args,text=True,timeout=20).strip()
def status():
    return dict(token.split('=',1) for token in run('sc132gs-ctl','status').split()[1:])
media=run('sc132gs-discover','media')
nodes=[run('media-ctl','-d',media,'-e','sc132gs '+name) for name in ('18-0032','16-0030')]
def short_minimum(rows):
    for node in nodes:
        run('v4l2-ctl','-d',node,f'--set-ctrl=hdr_total_nominal_rows={rows},hdr_total_second_ratio=256,hdr_second_exposure_ticks=1')

results=[]
try:
    for name,rows,gain in [('dark-seed',800,0),('bright-seed',1492,64)]:
        run('sc132gs-camera','apply','--ae','off','--hdr-total-rows',str(rows),
            '--gain-index',str(gain),'--brightness','30')
        short_minimum(rows)
        time.sleep(1)
        initial=status()
        run('sc132gs-camera','apply','--ae','on','--brightness','30')
        records=[]
        for index in range(36):
            records.append({'seconds':index,'status':status()})
            time.sleep(1)
        settled=records[-8:]
        good=all(s['status']['mode']=='auto' and s['status']['error_errno']=='0'
            and s['status']['display_gamma_x100']=='50'
            and abs(int(s['status']['cam0_percent'])-30)<=1
            and abs(int(s['status']['cam1_percent'])-30)<=1
            and s['status']['hdr_second_ticks']=='1'
            and int(s['status']['fps_x10'])>=290
            and max(int(s['status']['cam0_saturation_bp']),int(s['status']['cam1_saturation_bp']))<=500
            for s in settled)
        result={'case':name,'initial':initial,'records':records,'passed':good}
        results.append(result)
        (OUT/'ae-convergence-b.json').write_text(json.dumps(results,indent=2))
        print(json.dumps({'case':name,'passed':good,'final':records[-1]}),flush=True)
    if not all(result['passed'] for result in results):
        raise RuntimeError('AE convergence or stream check failed; inspect evidence')
except BaseException:
    run('sc132gs-camera','apply','--ae','off','--hdr-total-rows','1492','--gain-index','21','--brightness','30')
    short_minimum(1492)
    raise
