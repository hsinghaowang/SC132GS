"""Measure HDR short integration at fixed TOTAL/gain; restore AE configuration."""
import sys
import json
import time
sys.argv=['compare_modes','second-sweep','10','noise']
import compare_modes as probe

initial=dict(t.split('=',1) for t in probe.run('sc132gs-ctl','status').split()[1:])
if probe.saved['mode']!='hdr' or not probe.saved['ae']:
    raise RuntimeError('Requires current HDR AE profile')
media=probe.run('sc132gs-discover','media')
nodes=[probe.run('media-ctl','-d',media,'-e','sc132gs '+identity)
       for identity in ('18-0032','16-0030')]
results=[]
try:
    probe.run('sc132gs-camera','apply','--ae','off','--gain-index','0','--hdr-total-rows','1492')
    for second in (1,16,64,128,256,512,1):
        for node in nodes:
            probe.run('v4l2-ctl','-d',node,'--set-ctrl=hdr_second_exposure_ticks='+str(second))
        time.sleep(2)
        name=f'second-{second}-{len(results)}'
        result=dict(second_ticks=second,status=probe.run('sc132gs-ctl','status'),
                    decoded=probe.capture(name))
        results.append(result)
        (probe.OUT/'comparison.json').write_text(json.dumps(results,indent=2))
        print(json.dumps(result),flush=True)
finally:
    for node in nodes:
        probe.run('v4l2-ctl','-d',node,'--set-ctrl=hdr_second_exposure_ticks='+initial['hdr_second_ticks'])
    probe.run('sc132gs-camera','apply','--ae','on','--ae-target',str(probe.saved['brightness']),
              '--max-gain-index',str(probe.saved['max_gain_index']),
              '--max-exposure-us',str(probe.saved['max_exposure_us']))
    (probe.OUT/'restored-status.txt').write_text(probe.run('sc132gs-camera','status'))
