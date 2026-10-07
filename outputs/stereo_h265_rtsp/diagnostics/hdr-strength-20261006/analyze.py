import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


RAW = Path(r'D:/projects/collision_avoid/tmp/hdrc-ratio/strength-20261006')
OUT = Path(r'D:/projects/collision_avoid/outputs/stereo_h265_rtsp/diagnostics/hdr-strength-20261006')
evidence = json.loads((OUT / 'capture-evidence.json').read_text())
conditions = evidence['conditions']
LABELS = [c['label'] for c in conditions]
font_path = r'C:/Windows/Fonts/msyh.ttc'
BG, FG, MUTED = '#10151c', '#f1f5f9', '#b5c0cd'
ROI = (650, 660, 1080, 1060)
report = {'method': '12 original RAW10 frames per eye/condition; saturation RAW10 >=1020. Temporal variation includes sensor noise, scene motion and illumination flicker. Fixed masks from baseline. RTSP screenshots are decoded 8-bit output.',
          'frame_count_per_eye_condition': 12, 'gain_index': evidence['fixed_gain_index'],
          'conditions': [], 'comparison': []}
means, stds = {}, {}


def font(size):
    return ImageFont.truetype(font_path, size)


def unpack(path, expected_hashes):
    data = path.read_bytes()
    size = 1088 * 1280 * 5 // 4
    assert len(data) == 12 * size
    assert [hashlib.sha256(data[i*size:(i+1)*size]).hexdigest() for i in range(12)] == expected_hashes
    packed = np.frombuffer(data, np.uint8).reshape(12, 1280, 272, 5).astype(np.uint16)
    pixels = np.empty((12, 1280, 272, 4), np.uint16)
    for k in range(4):
        pixels[..., k] = (packed[..., k] << 2) | ((packed[..., 4] >> (2*k)) & 3)
    return pixels.reshape(12, 1280, 1088)


for eye in range(2):
    dark_mask = None
    for condition in conditions:
        label = condition['label']
        pixels = unpack(RAW / f'{label}-cam{eye}.raw', condition['raw'][eye]['sha256'])
        mean = pixels.mean(axis=0).astype(np.float32)
        std = pixels.astype(np.float32).std(axis=0)
        means[eye, label], stds[eye, label] = mean, std
        mirrored = pixels[:, :, ::-1]
        if dark_mask is None:
            dark_mask = (mean > 20) & (mean < 200)
            dark_mask[:120] = False
            dark_mask[1150:] = False
            dark_mask[:, :20] = False
            dark_mask[:, 980:] = False
        x0, y0, x1, y1 = ROI
        crop = mirrored[:, y0:y1, x0:x1]
        central = pixels[:, 320:960, 272:816]
        stats = {'label': label, 'eye': eye, 'total_over_second': condition['total_over_second'],
            'mean_raw10': float(mean.mean()), 'central_median_raw10': float(np.median(central)),
            'saturated_percent': float((pixels >= 1020).mean()*100),
            'highlight_crop_saturated_percent': float((crop >= 1020).mean()*100),
            'fixed_dark_mask_mean_raw10': float(mean[dark_mask].mean()),
            'fixed_dark_mask_temporal_std_median_raw10': float(np.median(std[dark_mask]))}
        report['conditions'].append(stats)
        # Identical fixed RAW10 scale and 2x2 RGGB -> BT.709 grayscale, mirrored
        # per eye as in RTSP. This diagnostic preview averages 12 RAW frames.
        luma = (54*mean[0::2, 0::2] + 183*(mean[0::2, 1::2] + mean[1::2, 0::2])/2 + 19*mean[1::2, 1::2]) / 256
        Image.fromarray(np.clip(np.rint(luma/4), 0, 255).astype(np.uint8)[:, ::-1]).save(OUT / f'{label}-cam{eye}-raw-mean.png')
        print(json.dumps(stats), flush=True)
        del pixels, mirrored, crop, central
    a, b = means[eye, LABELS[0]], means[eye, LABELS[-1]]
    stable = (np.abs(a-b) < 12) & (a > 20) & (a < 1000)
    ref = (a+b)/2
    report['comparison'].append({'eye': eye, 'condition': 'repeated-baseline',
        'mean_absolute_difference_raw10': float(np.abs(a-b).mean()),
        'stable_mask_fraction': float(stable.mean()),
        'stable_mask_mean_absolute_difference_raw10': float(np.abs(a-b)[stable].mean())})
    for label in LABELS[1:-1]:
        diff = means[eye, label] - ref
        report['comparison'].append({'eye': eye, 'condition': label,
            'vs_baseline_mean_absolute_difference_raw10': float(np.abs(diff).mean()),
            'stable_mask_mean_absolute_difference_raw10': float(np.abs(diff)[stable].mean()),
            'stable_mask_signed_mean_difference_raw10': float(diff[stable].mean())})


def statistics(eye, label):
    return next(s for s in report['conditions'] if s['eye'] == eye and s['label'] == label)


def build(rtsp=True, crop=False):
    selected = conditions[:4]
    pad, gap = 22, 18
    panel_w, panel_h = (430, 400) if crop else (435, 512)
    title_h, col_h, label_h, note_h, footer_h = 90, 70, 44, 44, 104
    width = 2*pad + 4*panel_w + 3*gap
    height = title_h + col_h + 2*(label_h + panel_h + note_h + gap) + footer_h
    canvas = Image.new('RGB', (width, height), BG)
    d = ImageDraw.Draw(canvas)
    title = 'HDR 曝光比例 — RTSP 燈具局部' if crop else ('HDR 曝光比例 — RTSP 截圖' if rtsp else 'HDR 曝光比例 — RAW 平均預覽')
    d.text((pad, 15), title, font=font(28), fill=FG)
    d.text((pad, 55), f'總曝光固定 0x5D40；兩眼增益固定 index {evidence["fixed_gain_index"]}；AE 關閉；HDR 30 FPS', font=font(20), fill=MUTED)
    for col, c in enumerate(selected):
        x = pad + col*(panel_w+gap)
        d.text((x, title_h), f'{c["total_over_second"]:.2f}:1' + ('（原設定）' if col == 0 else ''), font=font(25), fill='#70c6ff' if col == 0 else '#ffc26f')
        reg = c['raw_registers'][0]
        d.text((x, title_h+36), f'SECOND={reg["second"]:04X}   5400={reg["hdrc_ratio"]:02X}', font=font(18), fill=MUTED)
    for eye in range(2):
        y = title_h + col_h + eye*(label_h + panel_h + note_h + gap)
        d.text((pad, y), f'CAM{eye} — {"左眼" if eye == 0 else "右眼"}', font=font(23), fill=FG)
        for col, c in enumerate(selected):
            label = c['label']
            x = pad + col*(panel_w+gap)
            if rtsp:
                im = Image.open(OUT / f'{label}-rtsp.png').convert('RGB').crop((eye*1088, 0, (eye+1)*1088, 1280))
                if crop:
                    im = im.crop(ROI)
                else:
                    im = im.resize((panel_w, panel_h), Image.Resampling.LANCZOS)
            else:
                im = Image.open(OUT / f'{label}-cam{eye}-raw-mean.png').convert('RGB').resize((panel_w, panel_h), Image.Resampling.LANCZOS)
            canvas.paste(im, (x, y+label_h))
            s = statistics(eye, label)
            saturation = s['highlight_crop_saturated_percent'] if crop else s['saturated_percent']
            region = '燈具區域' if crop else '全畫面'
            d.text((x, y+label_h+panel_h+10), f'RAW {region}飽和：{saturation:.3f}%', font=font(19), fill=MUTED)
    y = height-footer_h+10
    d.text((pad, y), '所有條件使用相同顯示尺度；未額外調整對比、亮度、銳利度或降噪。', font=font(19), fill=MUTED)
    d.text((pad, y+31), '飽和統計來自每眼 12 張 RAW，定義為 RAW10 ≥1020；與 RTSP 截圖分段擷取。', font=font(19), fill=MUTED)
    d.text((pad, y+62), '局部圖為原始 RTSP 像素 1:1 裁切。' if crop else ('RAW 預覽使用 12 張平均、2×2 RGGB 灰階轉換；RTSP 圖為單張解碼影像。' if not rtsp else '原比例已在最後重拍，用於檢查照明與場景漂移。'), font=font(19), fill=MUTED)
    name = 'highlight-comparison.png' if crop else ('rtsp-comparison.png' if rtsp else 'raw-comparison.png')
    canvas.save(OUT / name)
    return str(OUT / name)


report['artifacts'] = [build(), build(crop=True), build(rtsp=False)]
(OUT / 'analysis.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'comparison': report['comparison'], 'artifacts': report['artifacts']}, indent=2))
