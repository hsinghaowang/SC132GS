#!/usr/bin/env python3
import importlib.util,json,pathlib,signal,subprocess,sys,time,fcntl,hashlib
spec=importlib.util.spec_from_file_location('h',pathlib.Path(__file__).with_name('hdr-strength-check.py'))
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
out=pathlib.Path(sys.argv[1]);out.mkdir(exist_ok=False)
initial=h.parsed(h.run('sc132gs-ctl','status'))
assert initial['hdr_enabled']=='1' and initial['hdr_ratio']=='256' and initial['gain_index']=='0',initial
h.run('sc132gs-ctl','auto','off')
media=h.run('sc132gs-discover','media')
paths=[h.run('media-ctl','-d',media,'-e','sc132gs '+name) for name in ('18-0032','16-0030')]
nodes=[h.run('sc132gs-discover',f'cam{i}') for i in range(2)]
report={'initial_status':initial,'conditions':[]}
generator=None;processes=[];handles=[]
lock=open('/run/sc132gs-mode.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
try:
    h.run('systemctl','stop',h.UNIT);h.run('configure-sc132gs-dual-pipeline');h.run('prepare-sc132gs-sync-gpios')
    log=open(out/'fsync.log','w');handles.append(log)
    generator=subprocess.Popen(['/usr/local/bin/sc132gs-fsync-generator','auto','18','19','30','100','active-low'],stdout=log,stderr=subprocess.STDOUT)
    for _ in range(100):
        if 'FSYNC generator armed' in (out/'fsync.log').read_text():break
        assert generator.poll() is None;time.sleep(.05)
    else:raise RuntimeError('FSYNC did not arm')
    generator.send_signal(signal.SIGUSR1)
    profiles=[('minimum',8),('medium',512),('current',int(initial['exposure_lines'])),('maximum',1492)]
    if len(sys.argv)>2 and sys.argv[2]=='--current-only':profiles=[('current',int(initial['exposure_lines']))]
    for label,rows in profiles:
        for p in paths:h.run('v4l2-ctl','-d',p,f'--set-ctrl=hdr_total_nominal_rows={rows},analogue_gain=0')
        processes=[]
        for eye,node in enumerate(nodes):
            log=open(out/f'{label}-cam{eye}.log','w');handles.append(log)
            processes.append(subprocess.Popen(['v4l2-ctl','-d',node,'--stream-mmap=4','--stream-poll','--stream-skip=60','--stream-count=12',f'--stream-to={out}/{label}-cam{eye}.raw'],stdout=log,stderr=subprocess.STDOUT))
        for c in h.CAMERAS:
            for _ in range(100):
                if h.read(*c,0x0100)[0]==1:break
                time.sleep(.01)
            else:raise RuntimeError('STREAMON missing')
        states=[h.state(*c) for c in h.CAMERAS];assert states[0]==states[1],states
        t=rows*16;second=max(1,(t+128)//256)
        assert states[0]['total']==t and states[0]['second']==second,states
        assert states[0]['hdrc_ratio']==(255*(t-second)+t//2)//t,states
        assert states[0]['long_gain']==[0,128,3,32],states
        for p in processes:assert p.wait(timeout=15)==0
        condition={'label':label,'total_rows':rows,'registers':states,'raw':[]}
        for eye in range(2):
            data=(out/f'{label}-cam{eye}.raw').read_bytes();assert len(data)==12*1740800
            hashes=[hashlib.sha256(data[i*1740800:(i+1)*1740800]).hexdigest() for i in range(12)]
            assert len(set(hashes))==12
            condition['raw'].append({'eye':eye,'sha256':hashes})
        report['conditions'].append(condition);(out/'evidence.json').write_text(json.dumps(report,indent=2))
        print(label+': '+json.dumps(states),flush=True)
except BaseException as e:report['error']=repr(e);raise
finally:
    for p in processes:
        if p.poll() is None:p.terminate();p.wait(timeout=5)
    if generator and generator.poll() is None:generator.terminate();generator.wait(timeout=5)
    for f in handles:f.close()
    fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
    h.run('sc132gs-ctl','set-mode','hdr');h.run('sc132gs-ctl','set-brightness','40');h.run('sc132gs-ctl','set-mode','hdr')
    report['final_status']=h.parsed(h.run('sc132gs-ctl','status'))
    (out/'evidence.json').write_text(json.dumps(report,indent=2));print('RESTORED '+json.dumps(report['final_status']),flush=True)
