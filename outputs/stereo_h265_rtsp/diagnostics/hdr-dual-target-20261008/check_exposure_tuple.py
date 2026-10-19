"""Check live clustered HDR controls with AE disabled; restore on exit."""
import json,pathlib,subprocess
def run(*args,check=True):
    return subprocess.run(args,text=True,capture_output=True,check=check)
def read(bus,addr,reg,n):
    return [int(s,16) for s in run('i2ctransfer','-f','-y',str(bus),f'w2@{addr}',hex(reg>>8),hex(reg&255),f'r{n}').stdout.split()]
status=run('sc132gs-ctl','status').stdout
assert 'mode=off ' in status,status
media=run('sc132gs-discover','media').stdout.strip()
results=[]
for bus,addr,name in ((18,'0x32','18-0032'),(16,'0x30','16-0030')):
    node=run('media-ctl','-d',media,'-e','sc132gs '+name).stdout.strip()
    def apply(rows,second,ratio=256,check=True):
        return run('v4l2-ctl','-d',node,f'--set-ctrl=hdr_total_nominal_rows={rows},hdr_total_second_ratio={ratio},hdr_second_exposure_ticks={second}',check=check)
    try:
        for rows,second in ((1492,93),(1492,1),(8,1),(1492,1492)):
            apply(rows,second)
            t=read(bus,addr,0x3e00,3);s=read(bus,addr,0x3e31,2)
            coefficient=read(bus,addr,0x5400,1)[0]
            assert ((t[0]&15)<<16|t[1]<<8|t[2])==rows*16
            assert (s[0]<<8|s[1])==second
            expected=(255*(rows*16-second)+rows*8)//(rows*16)
            assert coefficient==expected,(coefficient,expected)
            results.append(dict(eye=name,total=rows,second=second,coefficient=coefficient))
        before=read(bus,addr,0x3e00,3)+read(bus,addr,0x3e31,2)+read(bus,addr,0x5400,1)
        for rows,second,ratio in ((8,128,256),(1492,93,1),(1492,93,0)):
            assert apply(rows,second,ratio,False).returncode!=0
            after=read(bus,addr,0x3e00,3)+read(bus,addr,0x3e31,2)+read(bus,addr,0x5400,1)
            assert after==before
    finally: apply(1492,0)
path=pathlib.Path('/home/ubuntu/hdr-dual-target-20261008/tuple-check.json')
path.write_text(json.dumps(results,indent=2));print(json.dumps(results))
