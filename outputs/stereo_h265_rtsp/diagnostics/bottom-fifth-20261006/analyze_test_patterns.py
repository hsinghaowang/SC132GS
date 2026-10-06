import pathlib,sys,json
sys.path.insert(0,r'C:\Users\000403\AppData\Local\Temp\sc132gs-flicker-tools')
import numpy as np
from PIL import Image
root=pathlib.Path(__file__).parent
report={}
for path in root.glob('*-csid*.raw'):
    data=np.frombuffer(path.read_bytes(),np.uint8)
    print(path.name,'bytes',len(data))
    if len(data)!=1740800:continue
    data=data.reshape(1280,272,5)
    p=((data[...,:4].astype(np.uint16)<<2)|((data[...,4,None]>>np.arange(4,dtype=np.uint8)*2)&3)).reshape(1280,1088)
    Image.fromarray((p>>2).astype(np.uint8)).save(path.with_suffix('.png'))
    stats=[]
    for y in range(0,1280,128):
        c=p[y:y+128]
        stats.append(dict(row=y,mean=float(c.mean()),unique=len(np.unique(c)),
                          adjacent_row_difference=int(np.max(abs(c[1:].astype(int)-c[:-1].astype(int))))))
    report[path.name]=stats
gray=np.frombuffer((root/'encoder-solid.gray').read_bytes(),np.uint8).reshape(1280,2176)
report['encoder-solid']=[dict(row=y,mean=float(gray[y:y+128].mean()),std=float(gray[y:y+128].std()),
                              min=int(gray[y:y+128].min()),max=int(gray[y:y+128].max())) for y in range(0,1280,128)]
print(json.dumps(report,indent=2))
(root/'test-pattern-results.json').write_text(json.dumps(report,indent=2))
