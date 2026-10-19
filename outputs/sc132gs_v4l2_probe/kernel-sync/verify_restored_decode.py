#!/usr/bin/env python3
"""Bounded host Main10 decode; this is separate from raw DQBUF validation."""
import argparse, hashlib, json, sys, time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('output',type=Path);p.add_argument('--deps',type=Path)
p.add_argument('--url',default='rtsp://192.168.137.226:8554/stereo');a=p.parse_args()
if a.deps:sys.path.insert(0,str(a.deps.resolve()))
import av
import numpy as np
from PIL import Image
a.output.mkdir(parents=True,exist_ok=False)
frames=[];hashes=set();snapshot={};start=time.monotonic()
with av.open(a.url,options={'rtsp_transport':'tcp'},timeout=8) as container:
    stream=container.streams.video[0]
    for f in container.decode(stream):
        frames.append({'pts':f.pts,'time_base':str(f.time_base),'time':float(f.pts*f.time_base) if f.pts is not None else None,
                       'width':f.width,'height':f.height,'format':f.format.name})
        if len(frames)%30==0:hashes.add(hashlib.sha256(bytes(f.planes[0])).hexdigest())
        if len(frames)==60:
            assert f.format.name=='yuv420p10le'
            y=np.frombuffer(f.planes[0],dtype='<u2').reshape(f.height,f.planes[0].line_size//2)[:,:f.width]
            snapshot={'min':int(y.min()),'max':int(y.max()),'low_bits_present':bool(np.any(y%4)),
                      'eyes':[{'range':int(v.max()-v.min()),'mean':float(v.mean())} for v in np.hsplit(y,2)]}
            Image.fromarray((y>>2).astype('uint8')).save(a.output/'decoded.png')
        if len(frames)>=330 or time.monotonic()-start>22:break
valid=[f['time'] for f in frames[30:] if f['time'] is not None]
fps=(len(valid)-1)/(valid[-1]-valid[0]) if len(valid)>1 else 0
monotonic=all(b>a for a,b in zip(valid,valid[1:]))
result={'decoded_frames':len(frames),'steady_media_fps':fps,'steady_pts_monotonic':monotonic,
        'unique_sample_hashes':len(hashes),'snapshot':snapshot,'codec_profile':stream.codec_context.profile,
        'passed':len(frames)>=270 and 29.7<=fps<=30.3 and monotonic and len(hashes)>1 and
                 all((f['width'],f['height'],f['format'])==(2176,1280,'yuv420p10le') for f in frames) and
                 all(e['range']>16 for e in snapshot.get('eyes',[]))}
(a.output/'frames.json').write_text(json.dumps(frames,indent=2)+'\n')
(a.output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2));raise SystemExit(0 if result['passed'] else 1)
