"""Verify persistent HDR RAW10 target controls and live AE response."""
import json
from pathlib import Path
import subprocess
import time
import yaml

OUT=Path('/home/ubuntu/hdr-tuning-20261012/sensor-ae-target')
def run(*args):
    return subprocess.check_output(args,text=True,timeout=25).strip()
def status():
    return dict(token.split('=',1) for token in run('sc132gs-ctl','status').split()[1:])
initial=status()
saved=yaml.safe_load(Path('/var/lib/sc132gs-camera/settings.yaml').read_text())
results=[]
try:
    for target,seconds in ((8,24),(12,20),(70,20)):
        reply=run('sc132gs-camera','apply','--ae','on','--ae-target',str(target))
        records=[]
        for index in range(seconds):
            records.append({'seconds':index,'status':status()})
            time.sleep(1)
        settled=[item['status'] for item in records[-5:]]
        durable=yaml.safe_load(Path('/var/lib/sc132gs-camera/settings.yaml').read_text())
        passed=durable['brightness']==target and all(
            item['target_percent']==str(target) and
            item['effective_target_bp']==str(target*100) and
            item['hdr_target_raw10']==str((target*1023+50)//100) and
            item['target_kind']=='hdr_sensor_percent' and
            item['display_gamma_x100']=='100' and item['error_errno']=='0' and
            int(item['fps_x10'])>=290 for item in settled)
        if target<20:
            passed=passed and all(abs(int(item['cam0_percent'])-target)<=2 and
                abs(int(item['cam1_percent'])-target)<=2 for item in settled)
        else:
            passed=passed and all(item['brightness_limited']=='1' and
                item['highlight_limited']=='1' for item in settled)
        result=dict(target=target,reply=reply,passed=passed,records=records,durable=durable)
        results.append(result)
        (OUT/'live-target-validation.json').write_text(json.dumps(results,indent=2))
        print(json.dumps(dict(target=target,passed=passed,final=settled[-1])),flush=True)
    before=status()
    revision=yaml.safe_load(Path('/var/lib/sc132gs-camera/settings.yaml').read_text())['revision']
    rejected=[]
    for value in ('-1','101','abc'):
        process=subprocess.run(['sc132gs-camera','apply','--ae-target',value],capture_output=True,text=True,timeout=10)
        after=status()
        assert process.returncode!=0 and after['target_percent']==before['target_percent']
        assert yaml.safe_load(Path('/var/lib/sc132gs-camera/settings.yaml').read_text())['revision']==revision
        rejected.append({'value':value,'returncode':process.returncode,'error':process.stderr.strip()})
    (OUT/'invalid-target-validation.json').write_text(json.dumps(rejected,indent=2))
    if not all(item['passed'] for item in results):
        raise RuntimeError('Live target validation failed; inspect saved evidence')
finally:
    run('sc132gs-camera','apply','--ae','on' if saved['ae'] else 'off',
        '--ae-target',str(saved['brightness']))
    (OUT/'final-status.txt').write_text(run('sc132gs-ctl','status')+'\n')
    (OUT/'final-settings.yaml').write_text(Path('/var/lib/sc132gs-camera/settings.yaml').read_text())
