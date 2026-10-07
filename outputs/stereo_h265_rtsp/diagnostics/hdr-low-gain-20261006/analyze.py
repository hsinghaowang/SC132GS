from pathlib import Path
import hashlib
import json
import shutil
import numpy as np
from PIL import Image, ImageDraw, ImageFont

root = Path('D:/projects/collision_avoid')
raw = root / 'tmp/hdrc-ratio/low-gain-20261006'
out = root / 'outputs/stereo_h265_rtsp/diagnostics/hdr-low-gain-20261006'
out.mkdir(parents=True, exist_ok=True)
evidence = json.loads((raw/'capture-evidence.json').read_text())
(out/'capture-evidence.json').write_text(json.dumps(evidence, indent=2))
shutil.copyfile(raw/'restored-rtsp.png', out/'restored-rtsp.png')
stats = []
for condition in evidence['conditions']:
    label = condition['label']
    # Preserve the exact captured PNG bytes so evidence hashes remain valid.
    shutil.copyfile(raw/f'{label}-rtsp.png', out/f'{label}-rtsp.png')
    for eye in range(2):
        data = (raw/f'{label}-cam{eye}.raw').read_bytes()
        size = 1740800
        assert len(data) == 12*size
        assert [hashlib.sha256(data[i*size:(i+1)*size]).hexdigest() for i in range(12)] == condition['raw'][eye]['sha256']
        packed = np.frombuffer(data, np.uint8).reshape(12,1280,272,5).astype(np.uint16)
        pixels = np.empty((12,1280,272,4), np.uint16)
        for k in range(4): pixels[...,k] = (packed[...,k]<<2) | ((packed[...,4]>>(2*k))&3)
        pixels = pixels.reshape(12,1280,1088)
        mirrored = pixels[:,:,::-1]
        lamp = mirrored[:,660:1060,650:1080]
        stat = dict(label=label,eye=eye,gain_index=condition['gain_index'],ratio=condition['total_over_second'],
                    lamp_saturated_percent=float((lamp>=1020).mean()*100),
                    central_median_raw10=float(np.median(pixels[:,320:960,272:816])))
        stats.append(stat)
        print(json.dumps(stat),flush=True)
        mean=pixels.mean(axis=0)
        luma=(54*mean[0::2,0::2]+183*(mean[0::2,1::2]+mean[1::2,0::2])/2+19*mean[1::2,1::2])/256
        preview=np.clip(np.rint(luma/4),0,255).astype(np.uint8)[:,::-1]
        Image.fromarray(preview).save(out/f'{label}-cam{eye}-raw.png')
(out/'analysis.json').write_text(json.dumps(stats,indent=2))
# Offline display prototype is labelled separately from measured live output.
font=lambda n: ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',n)
labels=['original-before','unity-r2p74-before','unity-r256']
canvas=Image.new('RGB',(1382,1090),'#10151c');d=ImageDraw.Draw(canvas)
d.text((20,12),'HDR 低增益測試 — RAW 燈具局部',font=font(27),fill='white')
names=['原設定：增益約 3.5×','1× 增益／2.74:1','1× 增益／259:1']
for eye in range(2):
    y=65+eye*500
    d.text((20,y),f'CAM{eye} — '+('左眼' if eye==0 else '右眼'),font=font(21),fill='white')
    for i,label in enumerate(labels):
        x=20+i*450
        d.text((x,y+32),names[i],font=font(20),fill='#9ad4ff')
        im=Image.open(out/f'{label}-cam{eye}-raw.png').crop((325,330,540,530)).resize((430,400))
        canvas.paste(im,(x,y+65))
        s=next(s for s in stats if s['label']==label and s['eye']==eye)
        d.text((x,y+468),f'RAW 飽和 {s["lamp_saturated_percent"]:.3f}%',font=font(18),fill='white')
d.text((20,1060),'同一 RAW 顯示尺度；12 張平均；飽和定義 RAW10 ≥1020；無額外降噪或亮度調整。',font=font(18),fill='#b5c0cd')
canvas.save(out/'raw-highlight-comparison.png')
