from pathlib import Path
import hashlib,json,os,subprocess,time,socket,re
R=Path('/home/ubuntu/rtsp-demand-20261016');U='sc132gs-camera-rtsp.service'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def ctl():
 with socket.socket(socket.AF_UNIX,socket.SOCK_SEQPACKET) as s:
  s.settimeout(3);s.connect('/run/sc132gs-ae.sock');s.sendall(b'status');v=s.recv(8192).decode()
 assert v.startswith('ok ');return dict(x.split('=',1) for x in v.split() if '=' in x)
def state():
 ps=[]
 for p in Path('/proc').iterdir():
  if not p.name.isdigit():continue
  try:
   if os.readlink(p/'exe')!=str(R/'build/stereo-h265-rtsp'):continue
   fds=[os.readlink(x) for x in (p/'fd').iterdir()]
   ps.append(dict(pid=int(p.name),binary_sha256=sha(p/'exe'),video_fds=[v for v in fds if re.fullmatch('/dev/video[0-9]+',v)],fd_count=len(fds),video_maps=[x for x in (p/'maps').read_text().splitlines() if '/dev/video' in x],cpu_ticks=sum(map(int,(p/'stat').read_text().split()[13:15])),rss_kb=int(re.search(r'VmRSS:\s+(\d+)',(p/'status').read_text()).group(1)),private_plugin_loaded=str(R/'plugin-build/sys/v4l2/libgstvideo4linux2.so') in (p/'maps').read_text()))
  except OSError:pass
 sync=Path('/sys/bus/platform/devices/acb3000.camss/fsync_control').read_text()
 return dict(processes=ps,sync=dict(re.findall(r'(\w+)=([^\s]+)',sync)),vpu_instances=[p.name for p in Path('/sys/kernel/debug/msm_vidc/core').glob('inst_*')],power=[Path('/sys/bus/i2c/devices/'+x+'/power/runtime_status').read_text().strip() for x in ['18-0032','16-0030']])
life=json.loads((R/'lifecycle-accepted.json').read_text());decode=json.loads((R/'pc-decode.json').read_text());baseline=json.loads((R/'baseline.json').read_text())
firewall=json.loads((R/'firewall-restoration.json').read_text())
assert life['passed'] and decode['success'] and firewall['restored']
a=state();time.sleep(10);b=state();ae=ctl()
protected={p:sha(p)==digest for p,digest in baseline['files'].items()}
verified_package=subprocess.run(['dpkg','--verify','gstreamer1.0-plugins-qcom-good'],capture_output=True,text=True)
checks=dict(system_plugin_package_unchanged=verified_package.returncode==0 and not verified_package.stdout.strip(),no_video_mappings=all(not p['video_maps'] for p in b['processes']),firewall_restored=firewall['restored'] and 'codex-rtsp-demand-blackhole' not in subprocess.check_output(['iptables','-S','INPUT'],text=True),service_active=subprocess.check_output(['systemctl','is-active',U],text=True).strip()=='active',single_owner=len(b['processes'])==1,no_video_fds=all(not p['video_fds'] for p in b['processes']),vpu_instances_zero=not b['vpu_instances'],sensor_suspend=b['power']==['suspended','suspended'],fsync_stopped=b['sync']['running']=='0',fsync_healthy=b['sync']['error']=='0' and b['sync']['skipped']=='0',idle_no_pulses=a['sync']['pulses']==b['sync']['pulses'],private_plugin=all(p['private_plugin_loaded'] for p in b['processes']),protected_files=all(protected.values()),ae_preferences=all(ae[k]==baseline['ae'][k] for k in ['mode','target_percent','max_exposure_us','max_gain_index']),ae_healthy=ae['error_errno']=='0',same_process_across_lifecycle=b['processes'][0]['pid']==life['cases'][0]['result']['process'][0]['pid'],pc_decode=decode['success'],lifecycle=life['passed'])
assert all(checks.values()),checks
m=json.loads((R/'deployment.json').read_text());m['binary_sha256']=sha(R/'build/stereo-h265-rtsp');m['profile_sha256']=sha(R/'run-camera-profile.sh');(R/'deployment.json').write_text(json.dumps(m,indent=2))
files=['StereoRtspServer.cpp','DepthRtspEndpoint.hpp','DepthPipeline.cpp','CMakeLists.txt']
sources={n:sha(R/'source/outputs/stereo_h265_rtsp'/n) for n in files}
subprocess.run(['systemctl','stop','rtsp-demand-rollback-20261016.timer'],check=True)
assert subprocess.run(['systemctl','is-active','rtsp-demand-rollback-20261016.timer'],capture_output=True,text=True).stdout.strip()=='inactive'
out=R/'final';out.mkdir(exist_ok=False)
for name,args in [('dmesg',['dmesg']),('unit',['systemctl','cat',U]),('show',['systemctl','show',U])]:
 (out/(name+'.txt')).write_text(subprocess.check_output(args,text=True))
(out/'server.log').write_bytes(Path('/run/sc132gs-camera-server.log').read_bytes())
(out/'sync-events.txt').write_bytes(Path('/sys/kernel/debug/sc132gs_sync/events').read_bytes())
idle_cpu_core_percent=(b['processes'][0]['cpu_ticks']-a['processes'][0]['cpu_ticks'])/os.sysconf('SC_CLK_TCK')/10*100
result=dict(passed=True,idle_cpu_core_percent=idle_cpu_core_percent,checks=checks,state=b,idle_before=a,idle_duration_seconds=10,ae=ae,protected=protected,source_sha256=sources,deployment=m,lifecycle_case_count=len(life['cases']),rollback_timer_disarmed=True)
(R/'final-state.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
