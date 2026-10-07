import hashlib,json
from pathlib import Path
import numpy as np

root=Path('tmp/hdrc-ratio/managed-raw-20261006')
out=Path('outputs/stereo_h265_rtsp/diagnostics/hdr-managed-raw-20261006');out.mkdir(parents=True,exist_ok=True)
evidence=json.loads((root/'evidence.json').read_text())
(out/'evidence.json').write_text(json.dumps(evidence,indent=2))
stats=[]
for c in evidence['conditions']:
    for eye in range(2):
        data=(root/f'{c["label"]}-cam{eye}.raw').read_bytes();size=1740800
        assert len(data)==12*size
        assert [hashlib.sha256(data[i*size:(i+1)*size]).hexdigest() for i in range(12)]==c['raw'][eye]['sha256']
        packed=np.frombuffer(data,np.uint8).reshape(12,1280,272,5).astype(np.uint16)
        p=np.empty((12,1280,272,4),np.uint16)
        for k in range(4):p[...,k]=(packed[...,k]<<2)|((packed[...,4]>>(2*k))&3)
        p=p.reshape(12,1280,1088)
        stat=dict(label=c['label'],total_rows=c['total_rows'],eye=eye,
                  percentiles_raw10=np.percentile(p,[0,.1,1,5,50,99,100]).tolist(),
                  central_median_raw10=float(np.median(p[:,320:960,272:816])),
                  lamp_saturated_percent=float((p[:,:,::-1][:,660:1060,650:1080]>=1020).mean()*100))
        stats.append(stat);print(json.dumps(stat),flush=True)
(out/'analysis.json').write_text(json.dumps(stats,indent=2))
