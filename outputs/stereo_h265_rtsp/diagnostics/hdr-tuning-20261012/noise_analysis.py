"""Decoded-image diagnostics only; never modify camera/display output."""
import numpy as np

def analyze_patch(frames):
    frames=np.asarray(frames,dtype=np.float64)
    if frames.ndim!=3 or frames.shape[0]<3:
        raise ValueError('At least three patch frames are required')
    if not np.isfinite(frames).all():
        raise ValueError('Non-finite patch')
    reference=frames.mean(axis=0)
    centered=reference-reference.mean()
    variance=float(np.mean(centered**2))
    levels=frames.mean(axis=(1,2))
    if variance>1e-10:
        gains=np.mean((frames-levels[:,None,None])*centered,axis=(1,2))/variance
    else:
        gains=np.ones(len(frames))
    offsets=levels-gains*reference.mean()
    residual=frames-(gains[:,None,None]*reference+offsets[:,None,None])
    total=float(frames.std(axis=0,ddof=1).mean())
    local=float(residual.std(axis=0,ddof=1).mean())
    contrast=float(np.percentile(reference,90)-np.percentile(reference,10))
    return dict(mean=float(reference.mean()),contrast_p90_p10=contrast,
        temporal_noise=total,contrast_to_noise=contrast/total if total else None,
        affine_residual_noise=local,
        contrast_to_residual_noise=contrast/local if local else None,
        frame_mean_std=float(levels.std(ddof=1)),
        fitted_gain_range=[float(gains.min()),float(gains.max())],
        fitted_offset_range=[float(offsets.min()),float(offsets.max())])

if __name__=='__main__':
    # Verify the diagnostic separates uniform illumination modulation from
    # independent local noise without smoothing the source frames.
    rng=np.random.default_rng(20261012)
    pattern=np.linspace(50,150,64*64).reshape(64,64)
    gain=1+0.15*np.sin(np.arange(32)*2*np.pi/3)
    original=gain[:,None,None]*pattern+7*np.cos(np.arange(32))[:,None,None]
    original+=rng.normal(0,1,original.shape)
    check=analyze_patch(original)
    assert check['temporal_noise']>10
    assert 0.9<check['affine_residual_noise']<1.1,check
    check=analyze_patch(np.full((32,32,32),53.)+rng.normal(0,1,(32,32,32)))
    assert 0.9<check['affine_residual_noise']<1.1,check
    try: analyze_patch(np.zeros((1,32,32)))
    except ValueError: pass
    else: raise AssertionError('Missing frame-count validation')
    print('noise diagnostic checks passed')
