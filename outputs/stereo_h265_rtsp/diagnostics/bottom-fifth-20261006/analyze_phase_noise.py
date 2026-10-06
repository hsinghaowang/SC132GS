import pathlib,sys,json
sys.path.insert(0,r'C:\Users\000403\AppData\Local\Temp\sc132gs-flicker-tools')
import numpy as np
from PIL import Image,ImageDraw
root=pathlib.Path(__file__).parent
report={}
for eye in range(2):
    data=np.frombuffer((root/f'cam{eye}-gain54.raw').read_bytes(),np.uint8).reshape(3,1280,-1,5)
    p=((data[...,:4].astype(np.uint16)<<2)|((data[...,4,None]>>np.arange(4,dtype=np.uint8)*2)&3)).reshape(3,1280,1088).astype(np.int32)
    out=[]
    for image in p:
        q=np.pad(image,1,mode='reflect')
        cross=(q[1:-1,:-2]+q[1:-1,2:]+q[:-2,1:-1]+q[2:,1:-1]+2)//4
        diag=(q[:-2,:-2]+q[:-2,2:]+q[2:,:-2]+q[2:,2:]+2)//4
        hor=(q[1:-1,:-2]+q[1:-1,2:]+1)//2; ver=(q[:-2,1:-1]+q[2:,1:-1]+1)//2
        y,x=np.indices(image.shape); same=y%2==x%2
        r=np.where(same,np.where(y%2,diag,image),np.where(y%2,ver,hor))
        g=np.where(same,cross,image)
        b=np.where(same,np.where(y%2,image,diag),np.where(y%2,hor,ver))
        out.append(np.clip((54*r+183*g+19*b+512)>>10,0,255).astype(np.float32))
    out=np.stack(out)
    for band,start,end in [('upper',512,768),('bottom',1024,1280)]:
        crop=out[:,start:end,320:832]; mean=crop.mean(axis=0); noise=crop.std(axis=0,ddof=1)
        report[f'cam{eye}-{band}']={}
        for y in range(2):
            for x in range(2):
                n=noise[y::2,x::2]; m=mean[y::2,x::2]; valid=(m>25)&(m<220)
                report[f'cam{eye}-{band}'][f'{y}{x}']=float(np.median(n[valid]))
    image=out[0].astype(np.int16); q=np.pad(image,1,mode='reflect')
    weighted=np.zeros_like(image,dtype=np.int32); weights=np.zeros_like(image,dtype=np.int32)
    for y in range(3):
        for x in range(3):
            neighbor=q[y:y+1280,x:x+1088]
            weight=np.maximum(0,12-abs(neighbor-image)) * (4 if y==1 and x==1 else 2 if x==1 or y==1 else 1)
            weighted+=neighbor*weight; weights+=weight
    filtered=((weighted+weights//2)//weights).astype(np.uint8)
    Image.fromarray(filtered).save(root/f'cam{eye}-filtered-proposal.png')
    canvas=Image.new('RGB',(1024,300),'white');draw=ImageDraw.Draw(canvas)
    canvas.paste(Image.fromarray(image.astype(np.uint8)).crop((320,1024,832,1280)).convert('RGB'),(0,24))
    canvas.paste(Image.fromarray(filtered).crop((320,1024,832,1280)).convert('RGB'),(512,24))
    draw.text((8,5),'current bilinear luma',fill='black');draw.text((520,5),'edge-preserving spatial filtering proposal',fill='black')
    canvas.save(root/f'cam{eye}-filter-proposal.png')
print(json.dumps(report,indent=2))
(root/'phase-noise.json').write_text(json.dumps(report,indent=2))
