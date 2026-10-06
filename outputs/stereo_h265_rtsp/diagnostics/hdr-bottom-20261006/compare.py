import json
import pathlib
import sys
sys.path.insert(0, r"C:\Users\000403\AppData\Local\Temp\sc132gs-flicker-tools")
import numpy as np
from PIL import Image, ImageDraw

root = pathlib.Path(__file__).parent
report = {}
canvas = Image.new('RGB', (1024, 560), 'white')
draw = ImageDraw.Draw(canvas)
for eye, name in enumerate(('cam0', 'cam1')):
    before = Image.open(root / f'{name}-direct.png')
    after = Image.open(root / f'{name}-fixed.pgm')
    after.save(root / f'{name}-fixed.png')
    report[name] = {}
    for label, img in (('before', before), ('after', after)):
        p = np.array(img, dtype=np.float32)[640:1280]
        phases = np.stack([p[0::2,0::2],p[0::2,1::2],p[1::2,0::2],p[1::2,1::2]], axis=-1)
        mean = phases.mean(axis=-1)
        valid = (mean > 25) & (mean < 212)
        report[name][label] = dict(median_cell_spread=float(np.median(np.ptp(phases[valid],axis=-1))),
                                  phase_relative_median=np.median(phases[valid]/mean[valid,None],axis=0).tolist())
    # Native-size crops preserve the two-pixel grid for comparison.
    crop = (320, 900, 832, 1156)
    y = 24 + eye*280
    canvas.paste(before.crop(crop).convert('RGB'), (0,y))
    canvas.paste(after.crop(crop).convert('RGB'), (512,y))
    draw.text((8,y-20), f'{name}: before (same RAW)', fill='black')
    draw.text((520,y-20), f'{name}: after RGGB reconstruction', fill='black')
canvas.save(root/'same-raw-comparison.png')
(root/'comparison.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
