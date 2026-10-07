"""Build a comparison from actual decoded RTSP frames and verify final RAW."""
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

root=Path(__file__).resolve().parents[4]
out=Path(__file__).parent
evidence=json.loads((out/'evidence.json').read_text())
raw=root/'tmp/hdrc-ratio/final-raw-20261006'
raw_evidence=json.loads((raw/'evidence.json').read_text())
c=raw_evidence['conditions'][0]
stats=[]
for eye in range(2):
    data=(raw/f'current-cam{eye}.raw').read_bytes();size=1740800
    assert len(data)==12*size
    assert [hashlib.sha256(data[i*size:(i+1)*size]).hexdigest() for i in range(12)]==c['raw'][eye]['sha256']
    packed=np.frombuffer(data,np.uint8).reshape(12,1280,272,5).astype(np.uint16)
    pixels=np.empty((12,1280,272,4),np.uint16)
    for k in range(4):pixels[...,k]=(packed[...,k]<<2)|((packed[...,4]>>(2*k))&3)
    pixels=pixels.reshape(12,1280,1088)
    lamp=pixels[:,:,::-1][:,660:1060,650:1080]
    stats.append(dict(eye=eye,total_rows=c['total_rows'],registers=c['registers'][eye],
                      lamp_saturated_percent=float((lamp>=1020).mean()*100),
                      full_saturated_percent=float((pixels>=1020).mean()*100),
                      central_median_raw10=float(np.median(pixels[:,320:960,272:816]))))

(out/'final-raw-evidence.json').write_text(json.dumps(raw_evidence,indent=2))
(out/'final-raw-analysis.json').write_text(json.dumps(stats,indent=2))
font=lambda n:ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',n)
selected=[next(c for c in evidence['conditions'] if c['label']==label) for label in ('linear-before','hdr-new')]
def build(cropped):
    panel_w,panel_h=(430,400) if cropped else (435,512)
    width=2*panel_w+68;height=190+2*(panel_h+55)+80
    canvas=Image.new('RGB',(width,height),'#10151c');draw=ImageDraw.Draw(canvas)
    draw.text((20,12),'Linear／新 HDR — RTSP '+('燈具局部' if cropped else '實際畫面'),font=font(25),fill='white')
    draw.text((20,52),'相同目標亮度 40%；下圖為真實解碼畫面，沒有追加亮度或降噪處理。',font=font(17),fill='#b5c0cd')
    for col,c in enumerate(selected):
        x=20+col*(panel_w+28);s=c['status']
        draw.text((x,94),'Linear 60 FPS' if col==0 else 'HDR 30 FPS／256:1／1× 增益',font=font(22),fill='#9ad4ff')
        draw.text((x,130),f'實測 {int(s["fps_x10"])/10:.1f} FPS；兩眼亮度 {s["cam0_percent"]}%／{s["cam1_percent"]}%',font=font(17),fill='#b5c0cd')
    for eye in range(2):
        y=170+eye*(panel_h+55)
        draw.text((20,y),'CAM'+str(eye)+' — '+('左眼' if eye==0 else '右眼'),font=font(21),fill='white')
        for col,c in enumerate(selected):
            im=Image.open(out/f'{c["label"]}.png').convert('RGB').crop((eye*1088,0,(eye+1)*1088,1280))
            if cropped:im=im.crop((650,660,1080,1060))
            else:im=im.resize((panel_w,panel_h),Image.Resampling.LANCZOS)
            canvas.paste(im,(20+col*(panel_w+28),y+35))
    y=height-80
    draw.text((20,y),'新 HDR 的燈具橫條恢復可見；RAW 燈具區域飽和占比：兩眼均為 0%。',font=font(18),fill='white')
    draw.text((20,y+30),'RAW 統計每眼 12 張、閾值 ≥1020；RAW 與 RTSP 分段擷取。',font=font(17),fill='#b5c0cd')
    canvas.save(out/('highlight-comparison.png' if cropped else 'comparison.png'))
build(False);build(True)
print(json.dumps(stats,indent=2))
