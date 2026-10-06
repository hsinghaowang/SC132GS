import pathlib,sys,json
sys.path.insert(0,r'C:\Users\000403\AppData\Local\Temp\sc132gs-flicker-tools')
import numpy as np
from PIL import Image,ImageDraw
root=pathlib.Path(__file__).parent
canvas=Image.new('RGB',(1024,560),'white');draw=ImageDraw.Draw(canvas);report={}
for eye in range(2):
    for x,stage in [(0,'before'),(512,'after')]:
        image=Image.open(root/f'cam{eye}-gate-{stage}-unfiltered.pgm')
        canvas.paste(image.crop((320,1024,832,1280)).convert('RGB'),(x,eye*280+24))
        draw.text((x+8,eye*280+5),f'cam{eye}: HDR FSYNC 0x3225=' + ('0x04 (before)' if stage=='before' else '0x00 (after)'),fill='black')
    raw=np.frombuffer((root/f'cam{eye}-gate-final.raw').read_bytes(),np.uint8).reshape(3,1280,272,5)
    p=((raw[...,:4].astype(np.uint16)<<2)|((raw[...,4,None]>>np.arange(4,dtype=np.uint8)*2)&3)).reshape(3,1280,1088).astype(float)
    mean=p.mean(0);pad=np.pad(mean,2,mode='reflect')
    hp=mean-(pad[2:-2,:-4]+pad[2:-2,4:]+pad[:-4,2:-2]+pad[4:,2:-2])/4
    report[f'cam{eye}']=[dict(row=y,spatial_residual=float(np.median(abs(hp[y:y+128,320:832][(mean[y:y+128,320:832]>40)&(mean[y:y+128,320:832]<950)])))) for y in range(0,1280,128)]
canvas.save(root/'hdr-gate-before-after.png');(root/'gate-final-raw.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
