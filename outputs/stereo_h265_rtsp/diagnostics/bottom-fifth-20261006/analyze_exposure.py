import pathlib,sys,json
sys.path.insert(0,r'C:\Users\000403\AppData\Local\Temp\sc132gs-flicker-tools')
import numpy as np
from PIL import Image,ImageDraw
root=pathlib.Path(__file__).parent
report={};canvas=Image.new('RGB',(1536,560),'white');draw=ImageDraw.Draw(canvas)
for eye in range(2):
    for index,exposure in enumerate((200,808,2176)):
        name=f'cam{eye}-exposure{exposure}'
        data=np.frombuffer((root/f'{name}.raw').read_bytes(),np.uint8).reshape(3,1280,272,5)
        p=((data[...,:4].astype(np.uint16)<<2)|((data[...,4,None]>>np.arange(4,dtype=np.uint8)*2)&3)).reshape(3,1280,1088).astype(float)
        mean=p.mean(axis=0);temporal=p.std(axis=0,ddof=1)
        q=np.pad(mean,2,mode='reflect')
        highpass=mean-(q[2:-2,:-4]+q[2:-2,4:]+q[:-4,2:-2]+q[4:,2:-2])/4
        result=[]
        for y in range(0,1280,128):
            m=mean[y:y+128,320:832];noise=temporal[y:y+128,320:832];hp=highpass[y:y+128,320:832]
            valid=(m>40)&(m<950)
            result.append(dict(row=y,mean=float(np.median(m[valid])),temporal_noise=float(np.median(noise[valid])),
                               spatial_residual=float(np.median(abs(hp[valid])))))
        report[name]=result
        img=np.asarray(Image.open(root/f'{name}.pgm'),dtype=float)[1024:1280,320:832]
        # Normalize each crop only for diagnostic visibility, not deployed output.
        valid=(img>10)&(img<230);factor=110/np.median(img[valid])
        view=Image.fromarray(np.clip(img*factor,0,255).astype(np.uint8))
        canvas.paste(view.convert('RGB'),(index*512,eye*280+24))
        draw.text((index*512+8,eye*280+5),f'{name} (display-normalized)',fill='black')
(root/'exposure-ab.json').write_text(json.dumps(report,indent=2))
canvas.save(root/'exposure-ab.png')
for name,rows in report.items():print(name,[(r['row'],round(r['mean'],1),round(r['temporal_noise'],1),round(r['spatial_residual'],1)) for r in rows])
