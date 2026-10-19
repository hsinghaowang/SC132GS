"""Assess saved mode comparisons without changing camera or image samples."""
import json
import sys
from pathlib import Path
import numpy as np


def assess(directory):
    directory = Path(directory)
    records = json.loads((directory / 'comparison.json').read_text())
    indexed = {(r['target'], r['mode']): r for r in records}
    results = []
    for target in sorted({r['target'] for r in records}):
        if (target, 'linear') not in indexed or (target, 'hdr') not in indexed:
            continue
        linear = indexed[target, 'linear']
        hdr = indexed[target, 'hdr']
        images = [np.load(directory / f'{mode}-{target}.npy') for mode in ('linear', 'hdr')]
        eyes = []
        for eye in range(2):
            left, right = [np.hsplit(image, 2)[eye] for image in images]
            h, w = left.shape
            left, right = [image[h//10:h*9//10, w//10:w*9//10] for image in (left, right)]
            threshold = float(np.percentile(left, 90))
            # Same spatial mask in both images; include the discarded top-10%
            # result separately so the global-brightness difference stays visible.
            common = left <= threshold
            bands=[]
            for low,high in ((0,10),(10,25),(25,50),(50,75),(75,90),(90,100)):
                lower=float(np.percentile(left,low))
                upper=float(np.percentile(left,high))
                mask=(left>=lower)&(left<=upper if high==100 else left<upper)
                bands.append(dict(linear_percentiles=[low,high],pixels=int(mask.sum()),
                    linear_mean=float(left[mask].mean()),hdr_mean=float(right[mask].mean())))
            eyes.append(dict(
                eye=eye,
                common_spatial_bands=bands,
                median_linear=float(np.median(left)), median_hdr=float(np.median(right)),
                global_mean_linear=float(left.mean()), global_mean_hdr=float(right.mean()),
                non_highlight_mean_linear=float(left[common].mean()),
                non_highlight_mean_hdr=float(right[common].mean()),
                non_highlight_change_percent=float((right[common].mean()/left[common].mean()-1)*100),
                clipped_linear_percent=float(np.mean(left >= 1020)*100),
                clipped_hdr_percent=float(np.mean(right >= 1020)*100)))
        patches = []
        for l, r in zip(linear['decoded']['dark_patches'], hdr['decoded']['dark_patches']):
            if (l['eye'], l['box']) != (r['eye'], r['box']):
                raise ValueError('Patch mismatch')
            patches.append(dict(eye=l['eye'], box=l['box'],
                linear_cnr=l['contrast_to_residual_noise'], hdr_cnr=r['contrast_to_residual_noise'],
                cnr_change_percent=(r['contrast_to_residual_noise']/l['contrast_to_residual_noise']-1)*100))
        results.append(dict(target=target, eyes=eyes, decoded_dark_patches=patches,
                            linear_status=linear['status'], hdr_status=hdr['status']))
    (directory/'assessment.json').write_text(json.dumps(results, indent=2)+'\n')
    return results


if __name__ == '__main__':
    for directory in sys.argv[1:]:
        print(json.dumps(dict(directory=directory, results=assess(directory)), indent=2))
