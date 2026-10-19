from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
import json,hashlib,sys
root=Path(__file__).parent
out=root/'board'
if len(sys.argv)>1:
    out=out/sys.argv[1]
    root=root/sys.argv[1]
    root.mkdir(exist_ok=True)
report=json.loads((out/'evidence.json').read_text())
stats=[]
previews=[]
for eye in range(2):
    data=(out/f'cam{eye}.raw').read_bytes()
    assert [hashlib.sha256(data[i*1740800:(i+1)*1740800]).hexdigest() for i in range(12)]==report['raw'][eye]['sha256']
    q=np.frombuffer(data,np.uint8).reshape(12,1280,272,5)
    raw=((q[...,:4].astype(np.uint16)<<2)|((q[...,4,None]>>np.arange(4,dtype=np.uint8)*2)&3)).reshape(12,1280,1088).astype(np.float32)
    mean=raw.mean(0)
    # Simple direct RAW preview: no Bayer interpolation or encoder.
    preview=np.rint(255*np.clip((mean-52)/971,0,1)**.38).astype(np.uint8)[:,::-1]
    Image.fromarray(preview).save(root/f'raw-eye{eye}.png')
    previews.append(preview)
    pad=np.pad(mean,2,mode='reflect')
    hp=mean-(pad[2:-2,:-4]+pad[2:-2,4:]+pad[:-4,2:-2]+pad[4:,2:-2])/4
    for start in range(0,1280,128):
        area=mean[start:start+128,320:832]; valid=(area>40)&(area<950)
        stats.append(dict(eye=eye,row=start,median=float(np.median(area)),q01=float(np.quantile(area,.01)),q05=float(np.quantile(area,.05)),spatial_residual=float(np.median(np.abs(hp[start:start+128,320:832][valid]))),temporal_noise=float(np.median(raw[:,start:start+128,320:832].std(0,ddof=1)[valid]))))
    np.savetxt(root/f'raw-eye{eye}-row-quantiles.csv',np.stack([np.arange(1280),np.quantile(mean,.01,axis=1),np.quantile(mean,.05,axis=1),np.median(mean,axis=1)],axis=1),delimiter=',',header='row,q01,q05,median',comments='')
Image.fromarray(np.concatenate(previews,axis=1)).save(root/'raw-direct-preview.png')
if (out/'decoded/decoded-luma10.u16le').exists():
    decoded=np.fromfile(out/'decoded/decoded-luma10.u16le',dtype='<u2').reshape(1280,2176)
    Image.fromarray(np.rint(255*np.clip((decoded.astype(float)-52)/971,0,1)**.38).astype(np.uint8)).save(root/'decoded-preview.png')
(root/'analysis.json').write_text(json.dumps(stats,indent=2))
print(json.dumps(stats,indent=2))
