"""Scene spatial residuals, not calibrated FPN; preserved means remain untouched."""
import json
import re
from pathlib import Path
import numpy as np
from PIL import Image

ROOT=Path(__file__).parent

def luma(raw):
    pad=np.pad(raw,1,mode='reflect')
    cross=(pad[:-2,1:-1]+pad[2:,1:-1]+pad[1:-1,:-2]+pad[1:-1,2:])/4
    diagonal=(pad[:-2,:-2]+pad[:-2,2:]+pad[2:,:-2]+pad[2:,2:])/4
    horizontal=(pad[1:-1,:-2]+pad[1:-1,2:])/2
    vertical=(pad[:-2,1:-1]+pad[2:,1:-1])/2
    y,x=np.indices(raw.shape)
    r=np.where(y%2==0,np.where(x%2==0,raw,horizontal),np.where(x%2==0,vertical,diagonal))
    g=np.where(y%2==x%2,cross,raw)
    b=np.where(y%2==1,np.where(x%2==1,raw,horizontal),np.where(x%2==1,vertical,diagonal))
    return (54*r+183*g+19*b)/256

report=dict(method='Same CFA four-neighbor high-pass of 32-frame mean, x=320..831, '
    '128-row bands, valid RAW=40..950, same method as 2026-10-06/08. '
    'Includes real texture; neither FPN calibration nor SNR.',cases=[])
for folder in ('haze-lit-means','haze-timing-means','haze-signal-means',
        'haze-vendor-reset-means','haze-second-wide-means',
        'haze-register-claims-means','haze-free-static-means'):
    root=ROOT/folder
    if not (root/'comparison.json').exists(): continue
    comparison=json.loads((root/'comparison.json').read_text())
    for case in comparison['cases']:
        if 'eyes' not in case: continue
        record=dict(source=folder,name=case['name'],configuration=case['configuration'],
            fsync_gpio_input_no_source=case.get('fsync_gpio_input_no_source',False),eyes=[])
        for eye in (0,1):
            path=root/case['name']/f'eye{eye}.mean.npy'
            mean=np.load(path)
            var=np.load(path.with_name(f'eye{eye}.temporal-var.npy'))
            pad=np.pad(mean,2,mode='reflect')
            hp=mean-(pad[2:-2,:-4]+pad[2:-2,4:]+pad[:-4,2:-2]+pad[4:,2:-2])/4
            bands=[]
            black=37 if case['configuration']['mode']=='linear' else 53
            for row in range(0,1280,128):
                sl=np.s_[row:row+128,320:832]
                area=mean[sl]; valid=(area>40)&(area<950)
                residual=np.abs(hp[sl])
                high_signal=valid&(area>black+20)
                bands.append(dict(row=row,median=float(np.median(area)),
                    spatial_residual=float(np.median(residual[valid])),
                    relative_residual_percent=float(np.median(
                        residual[high_signal]/(area[high_signal]-black))*100),
                    temporal_noise=float(np.median(np.sqrt(var[sl][valid])))))
            gray=luma(mean)
            signal=np.clip((gray-black)/(1023-black),0,1)
            Image.fromarray(np.rint(signal*255).astype('uint8')).save(path.with_suffix('.luma.png'))
            times=np.array([float(t) for t in re.findall(r'ts: ([0-9.]+)',
                (path.parent/f'eye{eye}.log').read_text())])[-32:]
            rate=dict(measured_frames=len(times),
                eof_fps=float((len(times)-1)/(times[-1]-times[0])),
                median_frame_interval_ms=float(np.median(np.diff(times))*1000)) if len(times)>1 else {}
            record['eyes'].append(dict(eye=eye,bands=bands,rate=rate,
                sensor_luma_median=float(np.median(gray)),
                sensor_luma_clip_fraction=float(np.mean(gray>=1020)),
                sensor_raw_clip_fraction=float(np.mean(mean>=1020))))
        report['cases'].append(record)
(ROOT/'haze-spatial-analysis.json').write_text(json.dumps(report,indent=2)+'\n')
for case in report['cases']:
    print(case['name'],[(round(e['sensor_luma_median'],2),
        [round(b['spatial_residual'],2) for b in e['bands']]) for e in case['eyes']])
