import pathlib,sys
sys.path.insert(0,r'C:\Users\000403\AppData\Local\Temp\sc132gs-flicker-tools')
import numpy as np
from PIL import Image,ImageDraw
root=pathlib.Path(__file__).parent
old=root.parent/'hdr-bottom-20261006'
canvas=Image.new('RGB',(1280,560),'white')
draw=ImageDraw.Draw(canvas)
for i,(label,path,mirror) in enumerate([
    ('old RAW reconstructed',old/'cam0-fixed.png',False),
    ('old stream decoded',old/'after-stream.png',True),
    ('current stream decoded',root/'current.png',True),
    ('user screenshot',pathlib.Path(r'C:\Users\000403\AppData\Local\Temp\codex-clipboard-be539954-587c-4f37-bd80-2f216a230e61.png'),True)]):
    img=Image.open(path).convert('L')
    # Patches from near the center of left-eye bottom; avoid scene edges.
    if i==3: crop=(520,920,648,1048)
    elif mirror: crop=(600,1090,728,1218)
    else: crop=(360,1090,488,1218)
    canvas.paste(img.crop(crop).resize((256,256),Image.Resampling.NEAREST).convert('RGB'),(i*320,24))
    draw.text((i*320+5,5),label,fill='black')
    a=np.asarray(img,dtype=float)
    print(label)
    if i<3:
        for y in range(0,1280,128):
            c=a[y:y+128,100:1000]
            dx=c[:,1:]-c[:,:-1]; dy=c[1:]-c[:-1]
            print(y,'dx',round(np.median(abs(dx)),2),'dy',round(np.median(abs(dy)),2), 'std',round(c.std(),2))
    if i!=3:
        upper=(crop[0],crop[1]-256,crop[2],crop[3]-256)
        canvas.paste(img.crop(upper).resize((256,256),Image.Resampling.NEAREST).convert('RGB'),(i*320,300))
canvas.save(root/'patches.png')
