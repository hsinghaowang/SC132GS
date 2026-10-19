"""Capture fixed-setting HDR RAW, then restore the production stream."""
import pathlib, subprocess, time, signal, json, re, hashlib, sys

OUT=pathlib.Path('/home/ubuntu/hdr-two-stage-20261008')/sys.argv[1]
OUT.mkdir(exist_ok=True,parents=True)
def run(*args):
    p=subprocess.run(args, capture_output=True, text=True, timeout=30)
    if p.returncode: raise RuntimeError((args,p.stdout,p.stderr))
    return p.stdout.strip()
def read(bus,addr,reg,n=1):
    return run('i2ctransfer','-f','-y',str(bus),f'w2@{addr}',hex(reg>>8),hex(reg&255),f'r{n}')
initial=run('sc132gs-ctl','status')
fields=dict(re.findall(r'(\w+)=([^\s]+)',initial))
assert fields['hdr_enabled']=='1' and fields['gain_index']=='0',initial
rows=int(sys.argv[2])
ratio=int(sys.argv[3])
report={'initial':initial,'rows':rows,'raw':[]}
generator=None
captures=[]
files=[]
try:
    run('sc132gs-ctl','auto','off')
    run('systemctl','stop','sc132gs-camera-rtsp.service')
    run('configure-sc132gs-dual-pipeline')
    run('prepare-sc132gs-sync-gpios')
    media=run('sc132gs-discover','media')
    for name in ('18-0032','16-0030'):
        subdev=run('media-ctl','-d',media,'-e','sc132gs '+name)
        run('v4l2-ctl','-d',subdev,f'--set-ctrl=hdr_total_nominal_rows={rows},hdr_total_second_ratio={ratio},analogue_gain=0')
    log=open(OUT/'fsync.log','w');files.append(log)
    rate='30'
    report['trigger_hz']=int(rate)
    generator=subprocess.Popen(['sc132gs-fsync-generator','auto','18','19',rate,'100','active-low'],stdout=log,stderr=subprocess.STDOUT)
    for _ in range(100):
        if 'FSYNC generator armed' in (OUT/'fsync.log').read_text(): break
        if generator.poll() is not None: raise RuntimeError('FSYNC exited')
        time.sleep(.025)
    else: raise RuntimeError('FSYNC not ready')
    generator.send_signal(signal.SIGUSR1)
    for eye in range(2):
        log=open(OUT/f'cam{eye}.log','w');files.append(log)
        node=run('sc132gs-discover',f'cam{eye}')
        captures.append(subprocess.Popen(['v4l2-ctl','-d',node,'--stream-mmap=4','--stream-poll','--stream-skip=60','--stream-count=4',f'--stream-to={OUT}/cam{eye}.raw'],stdout=log,stderr=subprocess.STDOUT))
    time.sleep(.5)
    if False:
        # Previously tested vendor free-run selector; diagnostic only.
        for b,a in ((18,'0x32'),(16,'0x30')):
            assert read(b,a,0x3222)=='0x32'
            run('i2ctransfer','-f','-y',str(b),f'w3@{a}','0x32','0x22','0x30')
    report['registers']=[{'bus':b,'address':a,'stream':read(b,a,0x100),'hdr':read(b,a,0x3220),'trigger':read(b,a,0x3222),'gate':read(b,a,0x3225),'total':read(b,a,0x3e00,3),'second':read(b,a,0x3e31,2),'gain':read(b,a,0x3e06,4)} for b,a in ((18,'0x32'),(16,'0x30'))]
    for p in captures:
        if p.wait(timeout=15): raise RuntimeError('RAW capture failed')
    for eye in range(2):
        data=(OUT/f'cam{eye}.raw').read_bytes()
        assert len(data)==4*1740800,len(data)
        hashes=[hashlib.sha256(data[i*1740800:(i+1)*1740800]).hexdigest() for i in range(4)]
        assert len(set(hashes))==4
        report['raw'].append({'eye':eye,'sha256':hashes})
except BaseException as e:
    report['error']=repr(e)
    raise
finally:
    for p in captures:
        if p.poll() is None: p.terminate();p.wait(timeout=5)
    if generator and generator.poll() is None: generator.terminate();generator.wait(timeout=5)
    for f in files:f.close()
    # Reload only after the stream and all diagnostic processes have stopped.
    owners=subprocess.run(['fuser','/dev/video32','/dev/video33'],capture_output=True,text=True)
    if owners.returncode==1:
        run('modprobe','-r','iris_vpu');run('modprobe','iris_vpu')
    run('systemctl','start','sc132gs-camera-rtsp.service')
    for _ in range(80):
        try:
            report['restored']=run('sc132gs-ctl','set-brightness','40');break
        except RuntimeError:time.sleep(.25)
    else:report['restore_error']='AE socket not ready'
    (OUT/'evidence.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report),flush=True)

