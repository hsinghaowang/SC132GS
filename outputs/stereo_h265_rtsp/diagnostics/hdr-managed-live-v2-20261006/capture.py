#!/usr/bin/env python3
"""Verify real mode transitions, HDR AE policy and decoded RTSP output."""
import datetime
import importlib.util
import json
import pathlib
import subprocess
import sys
import time

spec=importlib.util.spec_from_file_location('capture',pathlib.Path(__file__).with_name('hdr-strength-check.py'))
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
h.Gst.init(None)
out=pathlib.Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=False)
report={'conditions':[],'checks':[]}
def save(): (out/'evidence.json').write_text(json.dumps(report,indent=2)+'\n')
def settle(target, hdr):
    until=time.monotonic()+30;stable=0
    while time.monotonic()<until:
        status=h.parsed(h.run('sc132gs-ctl','status'))
        assert status['error_errno']=='0',status
        assert status['hdr_enabled']==str(int(hdr)),status
        fps=int(status['fps_x10'])
        assert (270<=fps<=330) if hdr else (540<=fps<=660),status
        mean=(int(status['cam0_percent'])+int(status['cam1_percent']))/2
        stable=stable+1 if abs(mean-target)<=2 else 0
        if stable>=3:return status
        time.sleep(.5)
    raise RuntimeError(f'Brightness failed to settle: {status}')
def capture(label, hdr, target=40):
    status=settle(target,hdr)
    status=h.parsed(h.run('sc132gs-ctl','auto','off'))
    before=[h.state(*c) for c in h.CAMERAS]
    assert before[0]==before[1],before
    if hdr:
        assert status['hdr_ratio']=='256' and status['display_gamma_x100']=='38',status
        assert status['display_black_raw10']=='52',status
        assert status['gain_index']=='0',status
        t=int(status['exposure_lines'])*16
        second=max(1,(t+128)//256)
        assert before[0]['total']==t and before[0]['second']==second,before
        assert before[0]['hdrc_ratio']==(255*(t-second)+t//2)//t,before
        assert before[0]['hdr_mode']==0xc3 and before[0]['hdrc_enable']==1,before
        assert before[0]['long_gain']==[0,128,3,32],before
    image=h.rtsp_capture('rtsp://192.168.137.226:8554/stereo',out/f'{label}.png')
    after=[h.state(*c) for c in h.CAMERAS]
    assert before==after,(before,after)
    report['conditions'].append(dict(label=label,status=status,registers=before,rtsp=image))
    save();print(label+': '+json.dumps(status),flush=True)
    h.run('sc132gs-ctl','set-brightness',str(target))

try:
    report['kernel']=h.run('uname','-r')
    report['driver_srcversion']=h.run('modinfo','-F','srcversion','sc132gs')
    report['loaded_srcversion']=pathlib.Path('/sys/module/sc132gs/srcversion').read_text().strip()
    assert report['driver_srcversion']==report['loaded_srcversion']
    report['binary_hash']=h.run('sha256sum','/home/ubuntu/stereo-h265-rtsp/build/stereo-h265-rtsp')
    for label,mode in [('linear-before','linear'),('hdr-new','hdr')]:
        print(h.run('sc132gs-ctl','set-mode',mode),flush=True)
        h.run('sc132gs-ctl','set-brightness','40')
        capture(label,mode=='hdr')
    h.run('sc132gs-ctl','set-brightness','20');capture('hdr-target20',True,20)
    h.run('sc132gs-ctl','set-brightness','60');time.sleep(6)
    limit=h.parsed(h.run('sc132gs-ctl','status'))
    assert limit['gain_index']=='0' and limit['brightness_limited']=='1',limit
    report['checks'].append(dict(check='hdr-target60-reports-limit-without-raising-gain',status=limit));save()
    h.run('sc132gs-ctl','set-brightness','40');settle(40,True)
    h.run('sc132gs-ctl','auto','off')
    media=h.run('sc132gs-discover','media')
    paths=[h.run('media-ctl','-d',media,'-e','sc132gs '+name) for name in ('18-0032','16-0030')]
    for path in paths:
        before=h.state(*h.CAMERAS[paths.index(path)])
        for setting in ('exposure=809','hdr_total_second_ratio=1','hdr_total_nominal_rows=1493'):
            result=subprocess.run(['v4l2-ctl','-d',path,'--set-ctrl='+setting],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            assert result.returncode!=0,(path,setting,result.stdout)
            assert h.state(*h.CAMERAS[paths.index(path)])==before
            report['checks'].append(dict(check='invalid-control-rejected',sensor=path,setting=setting,output=result.stdout))
    save();h.run('sc132gs-ctl','set-brightness','40')
    for label,mode in [('linear-after','linear'),('hdr-repeat','hdr'),('hdr-same-mode','hdr')]:
        print(h.run('sc132gs-ctl','set-mode',mode),flush=True)
        capture(label,mode=='hdr')
except BaseException as error:
    report['error']=repr(error);save();raise
finally:
    h.run('sc132gs-ctl','set-mode','hdr')
    h.run('sc132gs-ctl','set-brightness','40')
    h.run('sc132gs-ctl','set-mode','hdr')
    report['final_status']=settle(40,True)
    report['final_mode']=h.parsed(h.run('sc132gs-ctl','mode'))
    report['final_rtsp']=h.rtsp_capture('rtsp://192.168.137.226:8554/stereo',out/'hdr-final.png')
    report['completed_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat();save()
    print('FINAL '+json.dumps(report['final_status']),flush=True)
