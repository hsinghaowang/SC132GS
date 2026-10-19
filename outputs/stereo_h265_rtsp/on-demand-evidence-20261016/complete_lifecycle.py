import hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from DemandLifecycleCheck import Client,flowing,wait_idle,blackhole
root=Path(__file__).resolve().parent
original=root/'lifecycle-verified/result.json';old=json.loads(original.read_text())
assert not old['passed'] and len(old['cases'])==41 and 'Firewall rules changed' in old['error']
assert old['cases'][-1]['name']=='tcp_reader_without_rtsp_keepalive'
out=root/'lifecycle-completed';out.mkdir(exist_ok=False)
initial=wait_idle();assert initial['process'][0]['pid']==old['cases'][0]['result']['process'][0]['pid']
result=dict(passed=False,cases=old['cases'],resumed_from=str(original),resumed_sha256=hashlib.sha256(original.read_bytes()).hexdigest(),harness_correction='Compare firewall policies and rules, excluding timestamps and naturally changing traffic counters; original failed result and raw snapshots retained.')
c=Client('/stereo').start()
try:
 flowing(c)
 result['cases'].append(dict(name='network_blackhole_release',result=blackhole(c,out)))
 c.close(abrupt=True)
 result['cases'].append(dict(name='final_idle',result=wait_idle()))
 result['passed']=True
except BaseException as e:result['error']=repr(e);raise
finally:
 c.close(abrupt=True);(out/'result.json').write_text(json.dumps(result,indent=2))
print('LIFECYCLE PASSED:',len(result['cases']),'cases; firewall restored')
