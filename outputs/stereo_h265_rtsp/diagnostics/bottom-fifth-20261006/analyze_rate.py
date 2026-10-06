import pathlib,sys,json
sys.path.insert(0,r'C:\Users\000403\AppData\Local\Temp\sc132gs-flicker-tools')
import numpy as np
from PIL import Image,ImageDraw
root=pathlib.Path(__file__).parent;report={}
canvas=Image.new('RGB',(1536,280),'white');draw=ImageDraw.Draw(canvas)
for i,rate in enumerate((20,25,30)):
    name=f'cam0-rate{rate}'
    data=np.frombuffer((root/f'{name}.raw').read_bytes(),np.uint8).reshape(3,1280,272,5)
    p=((data[...,:4].astype(np.uint16)<<2)|((data[...,4,None]>>np.arange(4,dtype=np.uint8)*2)&3)).reshape(3,1280,1088).astype(float).mean(0)
    q=np.pad(p,2,mode='reflect');hp=p-(q[2:-2,:-4]+q[2:-2,4:]+q[:-4,2:-2]+q[4:,2:-2])/4
    rows=[]
    for y in range(0,1280,128):
        c=p[y:y+128,320:832];valid=(c>40)&(c<950)
        rows.append(dict(row=y,spatial_residual=float(np.median(abs(hp[y:y+128,320:832][valid])))))
    report[name]=rows
    img=Image.open(root/f'{name}.pgm')
    canvas.paste(img.crop((320,1024,832,1280)).convert('RGB'),(i*512,24));draw.text((i*512+8,5),name,fill='black')
print(json.dumps(report,indent=2));(root/'rate-ab.json').write_text(json.dumps(report,indent=2));canvas.save(root/'rate-ab.png')
