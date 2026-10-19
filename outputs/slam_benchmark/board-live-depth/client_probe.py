"""Decode actual RTSP frames and recover the board monotonic timestamp watermark."""
from pathlib import Path
import concurrent.futures,json,socket,struct,sys,time
import av,cv2,numpy as np
ROOT=Path(__file__).resolve().parent
out=ROOT/sys.argv[1];out.mkdir(exist_ok=True);seconds=int(sys.argv[2]) if len(sys.argv)>2 else 20
def clock_offset():
    probes=[]
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as s:
        s.settimeout(.5)
        for nonce in range(40):
            a=time.perf_counter_ns();s.sendto(struct.pack('<Q',nonce),('192.168.137.226',8767))
            try:packet,_=s.recvfrom(128)
            except socket.timeout:continue
            b=time.perf_counter_ns();n,board=struct.unpack('<QQ',packet)
            if n==nonce:probes.append(dict(rtt_ns=b-a,offset_ns=board-(a+b)//2,pc_mid_ns=(a+b)//2))
    if not probes:raise RuntimeError('clock echo unavailable')
    return min(probes,key=lambda p:p['rtt_ns'])
def decode(kind,url):
    rows=[];deadline=time.monotonic()+40;container=None;error=None
    while time.monotonic()<deadline:
        try:container=av.open(url,options={'rtsp_transport':'tcp','fflags':'nobuffer','flags':'low_delay','max_delay':'0'},timeout=(4,4));break
        except Exception as e:error=str(e);time.sleep(.3)
    if container is None:return dict(kind=kind,error=error)
    start=time.monotonic();saved=False
    try:
        for frame in container.decode(video=0):
            pc=time.perf_counter_ns();row=dict(pc_ns=pc,pts=frame.pts,width=frame.width,height=frame.height)
            if kind=='depth':
                gray=frame.to_ndarray(format='gray');bits=[];ok=True
                for bit in range(64):
                    a=float(gray[-15:-9,17+bit*8:23+bit*8].mean());b=float(gray[-7:-1,17+bit*8:23+bit*8].mean())
                    if abs(a-b)<100:ok=False
                    bits.append(a>b)
                stamp=sum(int(one)<<i for i,one in enumerate(bits));row.update(stamp_ns=stamp,marker_ok=ok)
            rows.append(row)
            if not saved and time.monotonic()-start>1:
                cv2.imwrite(str(out/f'{kind}-decoded.png'),frame.to_ndarray(format='bgr24'));saved=True
            if time.monotonic()-start>=seconds:break
    except Exception as e:error=str(e)
    finally:container.close()
    return dict(kind=kind,rows=rows,error=error)
before=clock_offset()
with concurrent.futures.ThreadPoolExecutor(2) as pool:
    gray=pool.submit(decode,'gray','rtsp://192.168.137.226:8554/stereo')
    depth=pool.submit(decode,'depth','rtsp://192.168.137.226:8556/depth')
    result=dict(pc_clock='QueryPerformanceCounter via perf_counter_ns',pc_clock_resolution_s=time.get_clock_info('perf_counter').resolution,clock_before=before,gray=gray.result(),depth=depth.result())
try:result['clock_after']=clock_offset()
except Exception as e:result['clock_after_error']=str(e)
(out/'client.json').write_text(json.dumps(result,indent=2))
for kind in ['gray','depth']:
    rows=result[kind].get('rows',[]);print(kind,len(rows),result[kind].get('error'))
    if len(rows)>1:print('decode_fps',(len(rows)-1)*1e9/(rows[-1]['pc_ns']-rows[0]['pc_ns']))
if result['depth'].get('rows'):
    rows=[r for r in result['depth']['rows'] if r['marker_ok']]
    latency=np.array([(r['pc_ns']+before['offset_ns']-r['stamp_ns'])/1e6 for r in rows]);print('marker_valid',len(rows),'latency_ms',np.percentile(latency,[50,95,99]).tolist() if len(rows) else [])
