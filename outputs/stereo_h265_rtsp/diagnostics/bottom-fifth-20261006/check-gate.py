import pathlib,sys,json
sys.path.insert(0,r'C:\Users\000403\AppData\Local\Temp\sc132gs-flicker-tools')
import numpy as np
from PIL import Image,ImageDraw
root=pathlib.Path(__file__).parent; report={}
canvas=Image.new('RGB',(2048,280),'white');draw=ImageDraw.Draw(canvas)
for eye in range(1):
    for col,mode in enumerate(('slave','gate0','input40','gates')):
        name=f'cam{eye}-trigger-{mode}'
        data=np.frombuffer((root/f'{name}.raw').read_bytes(),np.uint8).reshape(3,1280,1360)
        q=data.reshape(3,1280,272,5)
        p=((q[...,:4].astype(np.uint16)<<2)|((q[...,4,None]>>np.arange(4,dtype=np.uint8)*2)&3)).reshape(3,1280,1088).astype(float)
        mean=p.mean(0);n=p.std(0,ddof=1);z=np.pad(mean,2,mode='reflect')
        hp=mean-(z[2:-2,:-4]+z[2:-2,4:]+z[:-4,2:-2]+z[4:,2:-2])/4
        result=[]
        for y in range(0,1280,128):
            changed=data[1:,y:y+128]!=data[:-1,y:y+128]
            m=mean[y:y+128,320:832];valid=(m>40)&(m<950)
            result.append(dict(row=y,changed_byte_fraction=float(changed.mean()),
                temporal_noise=float(np.median(n[y:y+128,320:832][valid])),
                spatial_residual=float(np.median(abs(hp[y:y+128,320:832][valid])))))
        report[name]=result
        image=Image.open(root/f'{name}.pgm')
        canvas.paste(image.crop((320,1024,832,1280)).convert('RGB'),(col*512,eye*280+24))
        draw.text((col*512+8,eye*280+5),name,fill='black')
for name,rows in report.items():print(name,[(r['row'],round(r['changed_byte_fraction'],3),round(r['temporal_noise'],1),round(r['spatial_residual'],1)) for r in rows])
(root/'gate-ab-results.json').write_text(json.dumps(report,indent=2));canvas.save(root/'gate-ab.png')
