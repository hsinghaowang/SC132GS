import pathlib,sys,json
sys.path.insert(0,r'C:\Users\000403\AppData\Local\Temp\sc132gs-flicker-tools')
import numpy as np
from PIL import Image,ImageDraw
root=pathlib.Path(__file__).parent
before=Image.open(root/'cam0-gain54.pgm'); after=Image.open(root/'cam0-denoise.pgm')
canvas=Image.new('RGB',(1024,280),'white');draw=ImageDraw.Draw(canvas)
for x,label,img in [(0,'Same RAW: before noise filtering',before),(512,'Same RAW: after edge-preserving filtering',after)]:
    canvas.paste(img.crop((320,1024,832,1280)).convert('RGB'),(x,24));draw.text((x+8,5),label,fill='black')
canvas.save(root/'same-raw-denoise.png')
report={}
for label,img in [('before',before),('after',after)]:
    v=np.asarray(img,dtype=float)[1024:1280,320:832]
    q=np.stack([v[::2,::2],v[::2,1::2],v[1::2,::2],v[1::2,1::2]],axis=-1)
    valid=(q.mean(-1)>25)&(q.mean(-1)<212)
    report[label]=dict(median_cell_spread=float(np.median(np.ptp(q[valid],axis=-1))))
(root/'denoise-comparison.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
