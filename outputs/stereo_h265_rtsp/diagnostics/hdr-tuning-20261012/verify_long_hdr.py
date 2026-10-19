"""Live owner exposure boundaries and gain-to-exposure trade; restore policy."""
import json
from pathlib import Path
import subprocess
import sys
import time
import yaml

ROOT=Path('/home/ubuntu/hdr-tuning-20261012')
OUT=ROOT/(sys.argv[1] if len(sys.argv)>1 else 'long-hdr-owner-check')
OUT.mkdir(exist_ok=False)
SAVED=Path('/var/lib/sc132gs-camera/settings.yaml')
saved=yaml.safe_load(SAVED.read_text())
(OUT/'before-settings.yaml').write_bytes(SAVED.read_bytes())
record={'boundaries': [], 'gain_trade': {}, 'restored': False}

def command(*arguments, reject=False):
    durable=SAVED.read_bytes()
    process=subprocess.run(arguments,text=True,capture_output=True,timeout=90)
    result={'arguments':arguments,'returncode':process.returncode,
            'stdout':process.stdout.strip(),'stderr':process.stderr.strip()}
    if reject:
        if process.returncode==0 or not any(code in process.stderr for code in
                ('code=invalid_argument','code=unsupported_configuration')):
            raise RuntimeError('Expected owner boundary rejection: '+str(result))
        if SAVED.read_bytes()!=durable:
            raise RuntimeError('Rejected request changed durable policy')
    else:
        if process.returncode:
            (OUT/f'command-failure-{time.time_ns()}.json').write_text(json.dumps(result,indent=2))
        process.check_returncode()
    return result

def status():
    return command('sc132gs-ctl','status')['stdout']

def tokens(text):
    return dict(item.split('=',1) for item in text.split()[1:])

def persist():
    (OUT/'check.json').write_text(json.dumps(record,indent=2)+'\n')

try:
    for fps,cap in ((30,1492),(24,2560),(20,3629),(15,4350)):
        if len(sys.argv)>2 and fps not in tuple(map(int,sys.argv[2].split(','))):
            continue
        entry={'fps':fps,'ceiling_rows':cap}
        entry['reject']=command('sc132gs-camera','apply','--mode','hdr',
            '--max-fps',str(fps),'--ae','off','--hdr-total-rows',str(cap+1),
            '--gain-index','0',reject=True)
        entry['accepted']=command('sc132gs-camera','apply','--mode','hdr',
            '--max-fps',str(fps),'--ae','off','--hdr-total-rows',str(cap),
            '--gain-index','0')
        entry['status']=status()
        measured=tokens(entry['status'])
        if int(measured['exposure_lines'])!=cap or int(measured['error_errno']):
            raise RuntimeError('Manual exposure readback failed')
        if abs(int(measured['fps_x10'])/10-fps)>fps*.025:
            raise RuntimeError('Manual ceiling missed trigger cadence')
        record['boundaries'].append(entry)
        persist()
    command('sc132gs-camera','apply','--mode','hdr','--max-fps','30',
        '--ae','on','--ae-target','15','--max-gain-index','128')
    time.sleep(15)
    before=status()
    command('sc132gs-camera','apply','--max-fps','20')
    time.sleep(20)
    after=status()
    record['gain_trade']={'before':before,'after':after}
    if int(tokens(before)['gain_index'])<=int(tokens(after)['gain_index']):
        raise RuntimeError('Lower FPS did not replace gain with exposure')
    if int(tokens(after)['error_errno']):
        raise RuntimeError('AE control error after FPS change')
    persist()
finally:
    restore_arguments=['sc132gs-camera','apply','--mode',saved['mode'],
        '--max-fps',str(saved['max_fps']),'--ae','on' if saved['ae'] else 'off',
        '--ae-target',str(saved['brightness']),'--max-gain-index',str(saved['max_gain_index']),
        '--max-exposure-us',str(saved['max_exposure_us']),'--gain-index',str(saved['gain'])]
    if not saved['ae']:
        if saved['mode']=='hdr':
            restore_arguments+=['--hdr-total-rows',str(saved['rows'])]
        else:
            sys.path.insert(0,'/home/ubuntu/stereo-h265-rtsp')
            import camera_platform as platform
            restore_arguments+=['--exposure-us',str(round(saved['rows']*1000000/
                platform.row_rate(saved['binning'],saved['fps'])))]
    record['restore']=command(*restore_arguments)
    after=tokens(status())
    if not saved['ae'] and (int(after['exposure_lines'])!=saved['rows'] or
                            int(after['gain_index'])!=saved['gain']):
        raise RuntimeError('Manual policy restoration mismatch')
    record['restored']=True
    persist()
    print(json.dumps(record),flush=True)
