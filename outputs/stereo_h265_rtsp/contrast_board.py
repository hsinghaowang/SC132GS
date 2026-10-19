"""Reversible, single-owner validation of the matching-oriented candidate."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,os,subprocess,time,shlex
ROOT=Path('/home/ubuntu/shared8-contrast-20261016-1740')
DROP=Path('/etc/systemd/system/sc132gs-camera-rtsp.service.d/98-shared8-detail.conf')
WATCH='shared8-contrast-restore-20261016'
MONITOR='shared8-contrast-live-20261016.service'
spec=importlib.util.spec_from_file_location('h',ROOT/'tone_board_harness.py');h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
def snapshot(name):
    out=ROOT/name;out.mkdir(exist_ok=False);h.evidence(out,name)
    h.write_json(out/'status.json',dict(unit=h.unit_state(),owners=h.camera_owners(),ae=h.try_ctl(),sync=h.sync_state()))
def disarm(suffix=''):h.run(['systemctl','stop',WATCH+suffix+'.timer'],check=False)
def arm(suffix=''):
    h.run(['systemd-run','--quiet','--unit='+WATCH+suffix,'--on-active=25min','--timer-property=AccuracySec=1s','--property=TimeoutStopSec=180s','python3',str(ROOT/'contrast_board.py'),'rollback'])
    assert h.run(['systemctl','is-active',WATCH+suffix+'.timer']).stdout.strip()=='active'
def guard():
    assert all(h.unchanged(ROOT).values()),'Protected files changed'
    assert h.software_identity()==h.baseline(ROOT)['software']
    owners=h.camera_owners();assert len(owners)==1 and owners[0]['exe']==str(h.original_binary(ROOT))
    assert h.healthy_sync(h.sync_state()) and h.try_ctl()['target_percent']=='10'
def rollback():
    h.run(['systemctl','stop',MONITOR],check=False)
    if DROP.exists():
        assert h.sha(DROP)==json.loads((ROOT/'deployment.json').read_text())['drop_sha256']
        snapshot('rollback-'+str(time.time_ns()));h.run(['systemctl','stop',h.UNIT]);DROP.unlink();h.run(['systemctl','daemon-reload'])
    result=h.restore(ROOT);disarm();disarm('-probe');disarm('-raw');h.write_json(ROOT/'rollback-result.json',result);return result
def capture():
    guard();arm('-raw');snapshot('before-raw')
    try:
        h.run(['systemctl','stop',h.UNIT]);assert not h.camera_owners()
        result=h.raw_capture(ROOT)
    finally:
        h.restore(ROOT);snapshot('after-raw');disarm('-raw')
    assert result['passed'],result
    return result
def probe():
    guard();arm('-probe');snapshot('before-range-probe-'+str(time.time_ns()))
    try:
        h.run(['systemctl','stop',h.UNIT]);assert not h.camera_owners()
        y=bytes(0 if x<32 else 255 if x>=224 else x for row in range(256) for x in range(256))
        frame=y+bytes([128])*(256*128);(ROOT/'range-pattern.nv12').write_bytes(frame*30)
        outcomes={}
        for name,colour in [('full','1:3:5:1'),('limited','bt709')]:
            args=['taskset','-c','4-6','gst-launch-1.0','-e','filesrc','location='+str(ROOT/'range-pattern.nv12'),'blocksize=98304','!','rawvideoparse','format=nv12','width=256','height=256','framerate=30/1','colorimetry='+colour,'!','video/x-raw,colorimetry='+colour,'!','v4l2h265enc','output-io-mode=mmap','capture-io-mode=mmap','extra-controls=controls,video_bitrate=10000000,vui_timing_info=1,prepend_sps_and_pps_to_idr=1','!','h265parse','!','filesink','location='+str(ROOT/(name+'-range-probe.h265'))]
            p=h.run(args,timeout=30,check=False);(ROOT/(name+'-range-probe.log')).write_text(p.stdout+p.stderr)
            outcomes[name]=dict(returncode=p.returncode,command=args)
        h.write_json(ROOT/'range-probe.json',outcomes)
    finally:
        h.restore(ROOT);snapshot('after-range-probe-'+str(time.time_ns()));disarm('-probe')
    return outcomes
def deploy():
    guard();assert not DROP.exists();assert '100% tests passed' in (ROOT/'build.log').read_text()
    assert 'PASS mono10 and limited Y8' in (ROOT/'gpu-check.log').read_text()
    accepted=json.loads((ROOT/'range-decision.json').read_text());video=accepted['video_range']
    assert video in ('limited','full')
    wrapper=ROOT/'run-detail8.sh';wrapper.write_text('#!/bin/bash\nset -euo pipefail\nexec '+str(ROOT/'build/stereo-h265-rtsp')+' "$@" --tone-map shared-detail --display-range '+video+'\n');wrapper.chmod(0o755)
    content='[Service]\nEnvironment="SERVER_BIN='+str(wrapper)+'"\nEnvironment="HEVC_PROFILE=main"\n'
    result=dict(started_utc=h.utc(),passed=False,binary_sha256=h.sha(ROOT/'build/stereo-h265-rtsp'),drop_sha256=hashlib.sha256(content.encode()).hexdigest(),video_range=video)
    h.write_json(ROOT/'deployment.json',result);snapshot('before-deploy');arm()
    try:
        old=h.sync_state()['fields']['session'];DROP.write_text(content)
        h.run(['systemctl','daemon-reload']);h.run(['systemctl','restart',h.UNIT],timeout=35)
        end=time.monotonic()+65
        while time.monotonic()<end:
            s=h.sync_state();log=h.read(h.SERVER_LOG)
            if s['fields']['session']!=old and h.healthy_sync(s) and 'detail_tone active=1' in log and 'depth_mono8' in log:break
            time.sleep(.25)
        else:raise RuntimeError('Candidate readiness timed out')
        h.configure(h.saved_seed(ROOT));time.sleep(1);h.restore_startup_settings_record(ROOT,1)
        assert all(h.unchanged(ROOT).values())
        result.update(passed=True,sync=h.sync_state(),ae=h.try_ctl());h.write_json(ROOT/'deployment.json',result);snapshot('after-deploy')
        h.run(['systemd-run','--quiet','--unit='+MONITOR,'--property=AllowedCPUs=1-3','--property=CPUQuota=50%','--property=Nice=10','python3','-u',str(ROOT/'live_monitor.py')])
    except BaseException as e:
        result.update(error=repr(e));h.write_json(ROOT/'deployment.json',result);rollback();raise
    return result
def finish():
    live=json.loads((ROOT/'live-600s/result.json').read_text());pc=json.loads((ROOT/'pc-acceptance.json').read_text());post=json.loads((ROOT/'pc-final.json').read_text())
    assert live['passed'] and pc['success'] and post['success']
    s=h.sync_state();ae=h.try_ctl();owners=h.camera_owners();unit=h.unit_state()
    env=dict(x.split('=',1) for x in shlex.split(unit['Environment']) if '=' in x)
    checks=dict(active=unit['ActiveState']=='active',sync=h.healthy_sync(s),session=s['fields']['session']==live['session'],skipped=s['fields']['skipped']=='0',ae=ae['mode']=='auto' and ae['target_percent']=='10' and ae['error_errno']=='0',owner=len(owners)==1 and owners[0]['exe']==str(ROOT/'build/stereo-h265-rtsp'),protected=all(h.unchanged(ROOT).values()),software=h.software_identity()==h.baseline(ROOT)['software'],map=env['GPU_RECTIFICATION_MAP']==h.baseline(ROOT)['comparison_rectification_map'],main=env['HEVC_PROFILE']=='main')
    deployment=json.loads((ROOT/'deployment.json').read_text())
    checks['candidate_binary']=h.sha(ROOT/'build/stereo-h265-rtsp')==deployment['binary_sha256']
    checks['owned_drop']=h.sha(DROP)==deployment['drop_sha256']
    manifest=json.loads((ROOT/'source-sha256.json').read_text())
    checks['source']=all(h.sha(ROOT/'source'/p)==sha for p,sha in manifest.items())
    assert all(checks.values()),checks
    snapshot('final-accepted');disarm()
    result=dict(passed=True,time_utc=h.utc(),checks=checks,ae=ae,sync=s,owners=owners,intent='keep accepted rectified detail8 stream active')
    h.write_json(ROOT/'final-state.json',result);return result
if __name__=='__main__':
    os.sched_setaffinity(0,{1,2,3});p=argparse.ArgumentParser();p.add_argument('action',choices=['probe','capture','deploy','rollback','finish']);a=p.parse_args();print(json.dumps(globals()[a.action](),indent=2))
