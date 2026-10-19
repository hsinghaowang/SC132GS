"""Run only after the user confirms BOTH lenses are covered. Restore AE settings."""
import json
import sys
import time
sys.argv=['compare_modes','black-calibration','20','noise']
import compare_modes as probe

if probe.saved['binning']:
    raise RuntimeError('This calibration requires the current unbinned profile')
initial=dict(token.split('=',1) for token in probe.run('sc132gs-ctl','status').split()[1:])
(probe.OUT/'before-live-status.json').write_text(json.dumps(initial,indent=2))
media=probe.run('sc132gs-discover','media')
nodes=[probe.run('media-ctl','-d',media,'-e','sc132gs '+identity)
    for identity in ('18-0032','16-0030')]
records=[]
try:
    for mode in ('linear','hdr'):
        for gain in (0,11,21):
            options=['--exposure-us','8000'] if mode=='linear' else ['--hdr-total-rows','1492']
            reply=probe.run('sc132gs-camera','apply','--mode',mode,'--max-fps','30',
                '--ae','off','--ae-target',str(probe.saved['brightness']),
                '--gain-index',str(gain),*options)
            if mode=='hdr':
                # Match the actual scene profile, rather than a ratio-derived
                # short-exposure seed installed during a mode switch.
                for node in nodes:
                    probe.run('v4l2-ctl','-d',node,'--set-ctrl=hdr_second_exposure_ticks=1')
            time.sleep(2)
            name=f'{mode}-gain{gain}'
            frame=probe.capture(name)
            pixels=probe.np.load(probe.OUT/(name+'.npy'))
            covered=float(probe.np.percentile(pixels,99))<200
            black=[dict(median=float(probe.np.median(eye)),
                p1=float(probe.np.percentile(eye,1)),p99=float(probe.np.percentile(eye,99)))
                for eye in probe.np.hsplit(pixels,2)]
            result=dict(mode=mode,gain=gain,reply=reply,status=probe.run('sc132gs-ctl','status'),black=black,
                covered_check=covered,decoded=frame)
            records.append(result)
            (probe.OUT/'black-calibration.json').write_text(json.dumps(records,indent=2))
            print(json.dumps(result),flush=True)
            if not covered: raise RuntimeError('Dark-frame check failed: confirm both lenses are fully covered')
finally:
    original=probe.saved
    rows=int(initial['exposure_lines'])
    manual=['--hdr-total-rows',str(rows)] if original['mode']=='hdr' else [
        '--exposure-us',str(round(rows*1000000/84000))]
    # Compare helper has no timing assumptions; this calibration is performed
    # on the current unbinned Linear/HDR profiles only.
    probe.run('sc132gs-camera','apply','--mode',original['mode'],'--max-fps',str(original['max_fps']),
        '--ae','on' if original['ae'] else 'off','--ae-target',str(original['brightness']),
        '--max-gain-index',str(original['max_gain_index']),
        '--max-exposure-us',str(original['max_exposure_us']),
        *([] if original['ae'] else ['--gain-index',initial['gain_index'],*manual]))
    if original['mode']=='hdr':
        for node in nodes:
            probe.run('v4l2-ctl','-d',node,'--set-ctrl=hdr_second_exposure_ticks='+initial['hdr_second_ticks'])
    (probe.OUT/'restored-status.txt').write_text(probe.run('sc132gs-camera','status')+'\n')
