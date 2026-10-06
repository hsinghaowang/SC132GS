import json
import pathlib
import sys
import numpy as np
from PIL import Image, ImageDraw

root = pathlib.Path(sys.argv[1])
labels = ['a-before', 'b-formula', 'a-after']
report = {'conditions': [], 'comparison': []}
averages = {}
tile_w, tile_h = 544, 640
canvas = Image.new('RGB', (tile_w * 3, (tile_h + 32) * 2), 'white')
draw = ImageDraw.Draw(canvas)
for eye in range(2):
    for col, label in enumerate(labels):
        raw = np.fromfile(root / f'{label}-cam{eye}.raw', dtype=np.uint8)
        packed = raw.reshape(12, 1280, 272, 5).astype(np.uint16)
        pixels = np.empty((12, 1280, 272, 4), dtype=np.uint16)
        for i in range(4):
            pixels[:, :, :, i] = (packed[:, :, :, i] << 2) | ((packed[:, :, :, 4] >> (2*i)) & 3)
        pixels = pixels.reshape(12, 1280, 1088)
        mean = pixels.mean(axis=0)
        averages[(eye, label)] = mean
        report['conditions'].append({'eye': eye, 'label': label,
            'mean_raw10': float(pixels.mean()), 'median_raw10': float(np.median(pixels)),
            'p99_raw10': float(np.percentile(pixels, 99)),
            'saturated_percent': float((pixels >= 1020).mean()*100),
            'temporal_std_median_raw10': float(np.median(pixels.astype(np.float32).std(axis=0)))})
        # Identical fixed display scale; 2x2 RGGB luminance, no percentile normalization.
        luma = (54*mean[0::2, 0::2] + 183*(mean[0::2, 1::2] + mean[1::2, 0::2])/2 + 19*mean[1::2, 1::2])/256
        tile = Image.fromarray(np.clip(np.rint(luma/4), 0, 255).astype(np.uint8))
        canvas.paste(tile, (col*tile_w, eye*(tile_h+32)+32))
        draw.text((col*tile_w+8, eye*(tile_h+32)+8),
                  f'CAM{eye} {label}: 0x{128 if col!=1 else 162:02X}', fill='black')
        tile.save(root / f'{label}-cam{eye}.png')
    a = averages[(eye, 'a-before')]
    b = averages[(eye, 'b-formula')]
    c = averages[(eye, 'a-after')]
    stable = (np.abs(c-a) < 12) & (a > 50) & (a < 1000)
    report['comparison'].append({'eye': eye,
        'a_repeat_mean_absolute_difference_raw10': float(np.abs(c-a).mean()),
        'b_vs_a_mean_absolute_difference_raw10': float(np.abs(b-(a+c)/2).mean()),
        'stable_pixel_fraction': float(stable.mean()),
        'b_vs_a_stable_signed_difference_raw10': float(np.median((b-(a+c)/2)[stable])),
        'b_vs_a_stable_absolute_difference_raw10': float(np.median(np.abs(b-(a+c)/2)[stable]))})
canvas.save(root / 'comparison.png')
(root / 'analysis.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report, indent=2))
