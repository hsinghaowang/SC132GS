"""Uniform-surface diagnostics. No calibration map is applied to live pixels."""
import json
from pathlib import Path
import numpy as np
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
except ImportError:
    plt=None

def gaussian_filter(pixels,sigma,mode):
    # Gaussian transfer function over reflected padding; analysis only.
    border=int(4*sigma)
    padded=np.pad(pixels,border,mode=mode)
    fy=np.fft.fftfreq(padded.shape[0])[:,None]
    fx=np.fft.rfftfreq(padded.shape[1])[None,:]
    transfer=np.exp(-2*np.pi**2*sigma**2*(fy**2+fx**2))
    blurred=np.fft.irfft2(np.fft.rfft2(padded)*transfer,s=padded.shape)
    return blurred[border:-border,border:-border]

ROOT=Path(__file__).parent
SOURCE=ROOT/'haze-flat-means'
meta=json.loads((SOURCE/'comparison.json').read_text())
report=dict(method='32-frame mean. Within each CFA phase remove Gaussian sigma15 '
    '(30 physical pixels) local background. Compare fixed high-frequency RMS and '
    'relative residual after black subtraction. Subtract mean temporal variance /32 '
    'from mean residual variance as a finite-sample approximation. Exclude margins, '
    'low signal, clipping and strong local gradients. Aggregate/correlation '
    'ROI is y=48..895, x=80..1007: preview shows a cable/scene boundary below. '
    'Full-row profiles are retained but the lower rows are not a flat standard. Uniform surface is human '
    'positioned, not a calibrated radiance standard.',cases=[],correlations=[])
maps={}; masks={}
for case in meta['cases']:
    name=case['name']; black=37 if case['configuration']['mode']=='linear' else 53
    item=dict(name=name,configuration=case['configuration'],eyes=[])
    for eye in (0,1):
        mean=np.load(SOURCE/name/f'eye{eye}.mean.npy')
        var=np.load(SOURCE/name/f'eye{eye}.temporal-var.npy')
        residual=np.zeros_like(mean); relative=np.zeros_like(mean); valid=np.zeros(mean.shape,bool)
        for dy,dx in ((0,0),(0,1),(1,0),(1,1)):
            phase=mean[dy::2,dx::2]
            bg=gaussian_filter(phase,sigma=15,mode='reflect')
            ry=phase-bg
            grad=np.hypot(*np.gradient(bg))
            ok=(phase>black+30)&(phase<950)&(grad<2)
            residual[dy::2,dx::2]=ry
            relative[dy::2,dx::2]=ry/np.maximum(bg-black,1)
            valid[dy::2,dx::2]=ok
        valid[:48]=False; valid[-48:]=False; valid[:,:80]=False; valid[:,-80:]=False
        aggregate=valid.copy(); aggregate[896:]=False
        maps[name,eye]=relative; masks[name,eye]=aggregate
        bands=[]
        for row in range(0,1280,128):
            sl=np.s_[row:row+128,:]; ok=valid[sl]
            hf=residual[sl][ok]; noise=var[sl][ok]
            bands.append(dict(row=row,valid_pixels=int(ok.sum()),
                signal_median=float(np.median((mean[sl]-black)[ok])),
                temporal_rms=float(np.sqrt(np.mean(noise))),
                residual_median_abs=float(np.median(np.abs(hf))),
                fixed_hf_rms=float(np.sqrt(max(0,float(np.mean(hf**2)-np.mean(noise)/32)))),
                relative_hf_rms_percent=float(np.sqrt(np.mean(relative[sl][ok]**2))*100),
                relative_hf_median_abs_percent=float(np.median(np.abs(relative[sl][ok]))*100)))
        item['eyes'].append(dict(eye=eye,valid_pixels=int(aggregate.sum()),bands=bands,
            fixed_hf_rms=float(np.sqrt(max(0,float(np.mean(residual[aggregate]**2)-np.mean(var[aggregate])/32)))),
            relative_hf_rms_percent=float(np.sqrt(np.mean(relative[aggregate]**2))*100)))
    report['cases'].append(item)
for left,right in (
    ('flat-linear30','flat-linear30-repeat'),
    ('flat-hdr-long4350','flat-hdr-long4350-repeat'),
    ('flat-linear30','flat-hdr-short15'),
    ('flat-linear30','flat-hdr-long4350'),
    ('flat-hdr-short15','flat-hdr-long4350')):
    for eye in (0,1):
        valid=masks[left,eye]&masks[right,eye]
        a=maps[left,eye][valid]; b=maps[right,eye][valid]
        report['correlations'].append(dict(left=left,right=right,eye=eye,
            pixels=int(valid.sum()),correlation=float(np.corrcoef(a,b)[0,1])))
(ROOT/'haze-flat-analysis.json').write_text(json.dumps(report,indent=2)+'\n')
if plt is not None:
    fig,axes=plt.subplots(1,2,figsize=(10,7),sharey=True,constrained_layout=True)
    for case in report['cases']:
        if case['name'].endswith('repeat'): continue
        for eye,ax in enumerate(axes):
            bands=[b for b in case['eyes'][eye]['bands'] if b['row']<896]
            ax.plot([b['relative_hf_rms_percent'] for b in bands],
                [b['row']+64 for b in bands],label=case['name'].removeprefix('flat-'),marker='o',ms=3)
    for eye,ax in enumerate(axes):
        ax.set_title(f'Camera {eye}, gain 0'); ax.set_xlabel('Relative spatial HF RMS (%)')
        ax.grid(alpha=.25)
    axes[0].set_ylabel('Sensor row'); axes[0].invert_yaxis(); axes[1].legend(fontsize=8)
    axes[0].set_ylim(896,0)
    fig.suptitle('Uniform-surface RAW: spatial texture vs HDR exposure\nGain 0; flat upper ROI; no live correction applied')
    fig.savefig(ROOT/'haze-flat-row-profiles.png',dpi=150)
for case in report['cases']:
    print(case['name'],[(e['eye'],round(e['fixed_hf_rms'],3),round(e['relative_hf_rms_percent'],3),
        [round(b['relative_hf_rms_percent'],2) for b in e['bands']]) for e in case['eyes']])
print(report['correlations'])
