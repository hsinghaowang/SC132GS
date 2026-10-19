"""RTSP lifecycle acceptance: actual RTP, independent clients, board resources."""
import argparse,hashlib,json,re,shlex,socket,struct,subprocess,threading,time
from pathlib import Path
SSH=['ssh','-o','BatchMode=yes','ubuntu@192.168.137.226']
class Client:
 def __init__(self,path):
  self.url='rtsp://192.168.137.226:8554'+path;self.sock=socket.create_connection(('192.168.137.226',8554),5);self.sock.settimeout(.5)
  self.cv=threading.Condition();self.responses={};self.cseq=0;self.markers=0;self.packets=0;self.last_rtp_timestamp=None;self.rtp_regressions=0;self.dead=False;self.error=None;self.session=None
  self.thread=threading.Thread(target=self.receive,daemon=True);self.thread.start()
 def receive(self):
  data=b''
  try:
   while not self.dead:
    try:chunk=self.sock.recv(65536)
    except socket.timeout:continue
    if not chunk:break
    data+=chunk
    while data:
     if data[0]==36:
      if len(data)<4:break
      n=int.from_bytes(data[2:4],'big')
      if len(data)<n+4:break
      if data[1]==0 and n>=12:
       self.packets+=1
       stamp=int.from_bytes(data[8:12],'big')
       if self.last_rtp_timestamp is not None and (stamp-self.last_rtp_timestamp)&0xffffffff>0x7fffffff:self.rtp_regressions+=1
       self.last_rtp_timestamp=stamp
       if data[5]&128:self.markers+=1
      data=data[n+4:]
     else:
      end=data.find(b'\r\n\r\n')
      if end<0:break
      lines=data[:end].decode().split('\r\n');h=dict(x.split(':',1) for x in lines[1:]);h={k.lower():v.strip() for k,v in h.items()};n=int(h.get('content-length',0))
      if len(data)<end+4+n:break
      with self.cv:self.responses[int(h['cseq'])]=(lines[0],h,data[end+4:end+4+n]);self.cv.notify_all()
      data=data[end+4+n:]
  except Exception as e:
   if not self.dead:self.error=repr(e)
  finally:
   with self.cv:self.cv.notify_all()
 def request(self,method,url=None,extra=''):
  self.cseq+=1;seq=self.cseq
  text=f'{method} {url or self.url} RTSP/1.0\r\nCSeq: {seq}\r\n'+(f'Session: {self.session}\r\n' if self.session else '')+extra+'\r\n'
  self.sock.sendall(text.encode())
  with self.cv:
   assert self.cv.wait_for(lambda:seq in self.responses,timeout=25),(method,self.error)
   r=self.responses.pop(seq)
  assert ' 200 ' in r[0],r
  return r
 def start(self):
  r=self.request('DESCRIBE',extra='Accept: application/sdp\r\n');sdp=r[2].decode();track=[x[10:] for x in sdp.splitlines() if x.startswith('a=control:') and x!='a=control:*'][-1]
  r=self.request('SETUP',track if track.startswith('rtsp:') else self.url+'/'+track,'Transport: RTP/AVP/TCP;unicast;interleaved=0-1\r\n');self.session=r[1]['session'].split(';')[0]
  self.request('PLAY');return self
 def close(self,abrupt=False):
  if self.dead:return
  if not abrupt and self.session:self.request('TEARDOWN')
  self.dead=True;self.thread.join(1)
  if abrupt:self.sock.setsockopt(socket.SOL_SOCKET,socket.SO_LINGER,struct.pack('hh',1,0))
  self.sock.close()
def board():
 code="""from pathlib import Path
import json,os,re
root=Path('/proc');process=[]
for p in root.iterdir():
 if not p.name.isdigit():continue
 try:
  exe=os.readlink(p/'exe')
  if exe!='/home/ubuntu/rtsp-demand-20261016/build/stereo-h265-rtsp':continue
  fds={x.name:os.readlink(x) for x in (p/'fd').iterdir()};stat=(p/'status').read_text()
  process.append(dict(pid=int(p.name),video_fds=[v for v in fds.values() if re.fullmatch('/dev/video[0-9]+',v)],fd_count=len(fds),threads=int(re.search(r'Threads:\\s+(\\d+)',stat).group(1)),rss_kb=int(re.search(r'VmRSS:\\s+(\\d+)',stat).group(1))))
 except (OSError,PermissionError):pass
sync=Path('/sys/bus/platform/devices/acb3000.camss/fsync_control').read_text()
listening=any(len(x.split())>3 and x.split()[1].endswith(':216A') and x.split()[3]=='0A' for x in Path('/proc/net/tcp').read_text().splitlines()[1:])
print(json.dumps(dict(listening=listening,vpu_sessions=[p.name for p in Path('/sys/kernel/debug/msm_vidc/core').glob('inst_*')],process=process,sync=dict(re.findall(r'(\\w+)=([^\\s]+)',sync)),power=[Path('/sys/bus/i2c/devices/'+x+'/power/runtime_status').read_text().strip() for x in ['18-0032','16-0030']])))
"""
 r=subprocess.run(SSH+['sudo -n python3 -'],input=code,capture_output=True,text=True,check=True,timeout=15)
 return json.loads(r.stdout)
def wait_idle(timeout=40):
 start=time.monotonic();history=[]
 while time.monotonic()-start<timeout:
  s=board();history.append(s)
  if s['listening'] and len(s['process'])==1 and not s['process'][0]['video_fds'] and not s['vpu_sessions'] and s['sync']['running']=='0' and s['power']==['suspended','suspended']:
   s['idle_latency_s']=time.monotonic()-start;return s
  time.sleep(.5)
 raise AssertionError(('resources not released',history[-1]))
def flowing(*clients):
 before=[c.markers for c in clients];time.sleep(3)
 rates=[(c.markers-a)/3 for c,a in zip(clients,before)];assert all(r>15 for r in rates),rates
 s=board();assert s['sync']['running']=='1' and s['sync']['error']=='0',s
 return dict(fps=rates,board=s)
def blackhole(client,out):
 peer,port=client.sock.getsockname()
 rule=['-p','tcp','-s',peer,'--sport',str(port),'-d','192.168.137.226','--dport','8554','-m','comment','--comment','codex-rtsp-demand-blackhole','-j','DROP']
 def remote(args):
  return subprocess.run(SSH+['sudo -n '+shlex.join(args)],capture_output=True,text=True,check=True,timeout=15).stdout
 before=remote(['iptables-save']);(out/'firewall-before.txt').write_text(before)
 remote(['iptables','-I','INPUT','1']+rule)
 try:return wait_idle(45)
 finally:
  remote(['iptables','-D','INPUT']+rule)
  after=remote(['iptables-save']);(out/'firewall-after.txt').write_text(after)
  def canonical(v):return '\n'.join(re.sub(r'\[\d+:\d+\]','[traffic-counters]',x) for x in v.splitlines() if x and not x.startswith('#'))
  restored=canonical(before)==canonical(after)
  (out/'firewall-restoration.json').write_text(json.dumps(dict(restored=restored,peer=peer,port=port,before_sha256=hashlib.sha256(canonical(before).encode()).hexdigest(),after_sha256=hashlib.sha256(canonical(after).encode()).hexdigest()),indent=2))
  assert restored,'Firewall rules changed'
def main():
 p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(exist_ok=True,parents=True)
 result={'passed':False,'cases':[]};clients=[]
 def case(name,fn):
  print(name,flush=True);v=fn();result['cases'].append(dict(name=name,result=v));(a.out/'result.json').write_text(json.dumps(result,indent=2));return v
 def open_client(path):
  c=Client(path);clients.append(c);return c.start()
 try:
  case('initial_idle',wait_idle)
  for path in ['/stereo','/depth']:
   c=open_client(path);case(path+'_alone',lambda:flowing(c));c.close();case(path+'_teardown_release',wait_idle)
  for order in [('/stereo','/depth'),('/depth','/stereo'),('/stereo','/stereo'),('/depth','/depth')]:
   c=open_client(order[0]);d=open_client(order[1]);case(str(order)+'_both',lambda:flowing(c,d));c.close(abrupt=True);case(str(order)+'_survivor',lambda:flowing(d));d.close(abrupt=True);case(str(order)+'_rst_release',wait_idle)
  for i in range(6):
   c=open_client('/stereo' if i%2==0 else '/depth');case('reconnect_'+str(i),lambda:flowing(c));c.close(abrupt=i%2==0);case('release_'+str(i),wait_idle)
  for path in ['/stereo','/depth']:
   c=open_client(path);case(path+'_before_pause',lambda:flowing(c));c.request('PAUSE');case(path+'_paused_release',wait_idle);c.request('PLAY');case(path+'_resumed',lambda:flowing(c));assert c.rtp_regressions==0,('RTP timestamp regression',path,c.rtp_regressions);c.close();case(path+'_resume_release',wait_idle)
   c=Client(path);clients.append(c);c.request('DESCRIBE',extra='Accept: application/sdp\r\n');case(path+'_describe_only_bounded',wait_idle);c.close(abrupt=True)
  c=open_client('/stereo');case('no_keepalive_initial',lambda:flowing(c));time.sleep(36);case('tcp_reader_without_rtsp_keepalive',lambda:flowing(c));case('network_blackhole_release',lambda:blackhole(c,a.out));c.close(abrupt=True)
  case('final_idle',wait_idle)
  result['passed']=True
 except BaseException as e:result['error']=repr(e);raise
 finally:
  for c in clients:
   try:c.close(abrupt=True)
   except OSError:pass
  (a.out/'result.json').write_text(json.dumps(result,indent=2))
if __name__=='__main__':main()
