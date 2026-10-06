import pathlib,sys,json
sys.path.insert(0,r'C:\Users\000403\AppData\Local\Temp\sc132gs-flicker-tools')
import numpy as np
from PIL import Image,ImageDraw
root=pathlib.Path(__file__).parent
report={}
canvas=Image.new('RGB',(1024,560),'white'); draw=ImageDraw.Draw(canvas)
for eye in range(2):
    for col,gain in enumerate((0,54)):
        name=f'cam{eye}-gain{gain}'
        img=Image.open(root/f'{name}.pgm')
        crop=img.crop((320,1024,832,1280))
        canvas.paste(crop.convert('RGB'),(col*512,eye*280+24))
        draw.text((col*512+8,eye*280+5),name,fill='black')
        data=np.frombuffer((root/f'{name}.raw').read_bytes(),np.uint8).reshape(3,1280,-1,5)
        p=((data[...,:4].astype(np.uint16)<<2)|((data[...,4,None]>>np.arange(4,dtype=np.uint8)*2)&3)).reshape(3,1280,1088).astype(float)
        # Three frames: high-pass signal separates fixed scene texture from temporal noise.
        result=[]
        for y in range(0,1280,128):
            c=p[:,y:y+128,320:832]
            m=c.mean(axis=0)
            valid=(m>80)&(m<950)
            noise=c.std(axis=0,ddof=1)
            result.append(dict(row=y,mean=float(m[valid].mean()),temporal_noise_median=float(np.median(noise[valid])),
                               relative_noise_median=float(np.median(noise[valid]/m[valid]))))
        report[name]=result
canvas.save(root/'gain-ab.png')
(root/'gain-ab.json').write_text(json.dumps(report,indent=2))
for name,rows in report.items():
    print(name,[(r['row'],round(r['mean'],1),round(r['temporal_noise_median'],1),round(r['relative_noise_median'],3)) for r in rows])
