"""Observe both mounts on the one RTSP server; preserve real Main10 pixels."""
from pathlib import Path
import concurrent.futures,json,sys,time
import av,cv2,numpy as np
OUT=Path(__file__).resolve().parent/'rectification-evidence-20261016'/sys.argv[1];OUT.mkdir(exist_ok=True)
seconds=int(sys.argv[2]);fault=len(sys.argv)>3 and sys.argv[3]=='fault'
def decode(kind):
    rows=[];saved=False;error=None;url='rtsp://192.168.137.226:8554/'+('stereo' if kind=='stereo' else 'depth')
    deadline=time.perf_counter()+30;container=None
    while time.perf_counter()<deadline:
        try:container=av.open(url,options={'rtsp_transport':'tcp','fflags':'nobuffer','flags':'low_delay','max_delay':'0'},timeout=(4,4));break
        except Exception as e:error=str(e);time.sleep(.2)
    if container is None:return dict(rows=rows,error=error)
    start=time.perf_counter()
    try:
        for frame in container.decode(video=0):
            now=time.perf_counter_ns();rows.append(dict(pc_ns=now,pts=frame.pts,seconds=float(frame.pts*frame.time_base),width=frame.width,height=frame.height,pixel_format=frame.format.name))
            if not saved and time.perf_counter()-start>1:
                cv2.imwrite(str(OUT/(kind+'.png')),frame.to_ndarray(format='bgr24'))
                if kind=='stereo':
                    assert '10' in frame.format.name
                    plane=np.frombuffer(frame.planes[0],'<u2').reshape(frame.height,frame.planes[0].line_size//2)[:,:frame.width].copy()
                    np.save(OUT/'stereo-y10.npy',plane,allow_pickle=False)
                saved=True
            if time.perf_counter()-start>=seconds:break
    except Exception as e:error=str(e)
    finally:container.close()
    return dict(rows=rows,error=error)
with concurrent.futures.ThreadPoolExecutor(2) as pool:
    tasks={k:pool.submit(decode,k) for k in ['stereo','depth']};data={k:f.result() for k,f in tasks.items()}
for kind,result in data.items():
    rows=result['rows']
    if len(rows)>1:
        result['observed_seconds']=(rows[-1]['pc_ns']-rows[0]['pc_ns'])/1e9
        result['decode_fps']=(len(rows)-1)*1e9/(rows[-1]['pc_ns']-rows[0]['pc_ns'])
        result['pts_monotonic']=all(b['pts']>a['pts'] for a,b in zip(rows,rows[1:]))
        result['max_pts_gap_s']=max(b['seconds']-a['seconds'] for a,b in zip(rows,rows[1:]))
    print(kind,len(rows),result.get('decode_fps'),result['error'])
(OUT/'client.json').write_text(json.dumps(data,indent=2)+'\n')
assert data['stereo']['rows'] and data['stereo']['pts_monotonic'] and data['stereo']['error'] is None
assert data['stereo']['observed_seconds']>=seconds-2,'stereo ended before the requested duration'
assert all(r['width']==2176 and r['height']==1280 and '10' in r['pixel_format'] for r in data['stereo']['rows'])
if fault:
    assert data['depth']['rows'] and data['stereo']['rows'][-1]['pc_ns']-data['depth']['rows'][-1]['pc_ns']>10e9
else:
    assert data['depth']['rows'] and data['depth']['error'] is None and data['depth']['pts_monotonic']
    assert data['depth']['observed_seconds']>=seconds-2,'depth ended before the requested duration'
