"""Save RAW and decoded comparison metrics; no image transformations."""
import json
from pathlib import Path
from assess_signal import assess

root=Path(__file__).resolve().parent
report={'cases':[]}
for decoded,raw in (('calibrated-hdr20-target20','raw-noise-hdr20-target20'),
                    ('calibrated-hdr15-target30','raw-noise-hdr15-target30')):
    raw_records=json.loads((root/raw/'comparison.json').read_text())
    modes={entry['mode']:entry for entry in raw_records['records']}
    patches=[]
    for linear,hdr in zip(modes['linear']['raw']['patches'],modes['hdr']['raw']['patches']):
        if (linear['eye'],linear['box'])!=(hdr['eye'],hdr['box']):
            raise ValueError('Mismatched patch coordinates')
        patches.append(dict(eye=linear['eye'],box=linear['box'],
            linear_cnr=linear['contrast_to_residual_noise'],
            hdr_cnr=hdr['contrast_to_residual_noise'],
            cnr_change_percent=100*(hdr['contrast_to_residual_noise']/linear['contrast_to_residual_noise']-1),
            linear_temporal_noise=linear['temporal_noise'],
            hdr_temporal_noise=hdr['temporal_noise'],
            temporal_noise_change_percent=100*(hdr['temporal_noise']/linear['temporal_noise']-1),
            linear_residual_noise=linear['affine_residual_noise'],
            hdr_residual_noise=hdr['affine_residual_noise']))
    report['cases'].append(dict(decoded_directory=decoded,raw_directory=raw,
        decoded=assess(root/decoded),raw_dark_patches=patches,
        raw_frames_per_eye={mode:modes[mode]['raw']['frames_per_eye'] for mode in modes},
        raw_receiver_fps={mode:modes[mode]['raw']['receiver_fps'] for mode in modes},
        raw_policy_restored=raw_records['restored']))
(root/'long-hdr-assessment.json').write_text(json.dumps(report,indent=2)+'\n')
for case in report['cases']:
    print(case['decoded_directory'])
    print('RAW CNR changes:',[round(p['cnr_change_percent'],2) for p in case['raw_dark_patches']])
    print('RAW temporal noise changes:',[round(p['temporal_noise_change_percent'],2) for p in case['raw_dark_patches']])
    print('decoded CNR changes:',[round(p['cnr_change_percent'],2) for p in case['decoded'][0]['decoded_dark_patches']])
    print('same spatial luma bands:',[eye['common_spatial_bands'] for eye in case['decoded'][0]['eyes']])
