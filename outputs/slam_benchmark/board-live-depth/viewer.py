"""Browser bridge: decode board RTSP only; no PC stereo processing."""
from collections import deque
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import json,signal,threading,time
import av,cv2
ROOT=Path(__file__).resolve().parent
stop=threading.Event();lock=threading.Lock();frames={};states={}
cv2.setNumThreads(2)
PAGE='''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>板端 GPU 即時深度</title>
<style>body{background:#14181c;color:#edf4fa;font:16px/1.6 system-ui;max-width:1280px;margin:20px auto;padding:12px}img{max-width:100%;background:#000}a{color:#87caff}.views{display:flex;gap:16px;align-items:flex-start}.views>div:first-child{width:66%}.views>div:last-child{width:33%}h1{font-size:24px}h2{font-size:18px}</style>
<h1>板端 GPU：校正灰階與深度</h1><p id="status">連線中…</p><div class="views"><div><h2>校正灰階 · 2176×1280</h2><img id="grayview" hidden></div><div><h2>深度 · 544×640</h2><img id="depthview" hidden></div></div>
<p>暖色近、冷色遠，黑色為無效區域；色尺 0.2–3.0 m。PC 僅解碼與顯示，校正與深度由板端 GPU 計算。</p>
<p>灰階左半 cam1、右半 cam0；左右眼身份依校正幾何推定，尚待遮鏡頭確認。深度以 cam1 為參考。尺度假設為 20 mm 方格，測距準確度尚未驗證。</p>
<p>同一個板端 RTSP server：灰階為原解析度 HEVC Main10，沿用原服務的曝光控制；彩色深度為 8-bit HEVC。瀏覽器畫面會轉成 JPEG 顯示。</p>
<p><a href="/gray.jpg" target="_blank">灰階原尺寸快照</a> · <a href="/depth.jpg" target="_blank">深度快照</a> · <a href="/status.json" target="_blank">狀態</a></p>
<script>const loaded={gray:false,depth:false};function show(k,live){let v=document.getElementById(k+'view');if(!live){v.hidden=true;v.removeAttribute('src');loaded[k]=false}else if(!loaded[k]){loaded[k]=true;v.src='/'+k+'.mjpg';v.hidden=false}v.onerror=()=>{v.hidden=true;loaded[k]=false}}setInterval(async()=>{try{let s=await(await fetch('/status.json',{cache:'no-store',signal:AbortSignal.timeout(1500)})).json();document.querySelector('#status').textContent=['gray','depth'].map(k=>`${k}：${s[k]?.live?'live':'等待板端 GPU 串流'} ${s[k]?.decode_fps?.toFixed(1)||0} FPS`).join(' ｜ ');for(let k of ['gray','depth'])show(k,s[k]?.live)}catch{for(let k of ['gray','depth'])show(k,false);document.querySelector('#status').textContent='預覽服務連線中…'}},1000)</script></html>'''
def decoder(kind,port,mount):
    arrivals=deque(maxlen=90);count=0
    while not stop.is_set():
        try:
            with av.open(f'rtsp://192.168.137.226:{port}/{mount}',options={'rtsp_transport':'tcp','fflags':'nobuffer','flags':'low_delay','max_delay':'0'},timeout=(4,4)) as container:
                for frame in container.decode(video=0):
                    if stop.is_set():break
                    now=time.perf_counter();arrivals.append(now);count+=1
                    image=frame.to_ndarray(format='bgr24');ok,jpeg=cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,85])
                    if not ok:continue
                    with lock:
                        frames[kind]=(count,now,jpeg.tobytes())
                        states[kind]=dict(width=frame.width,height=frame.height,pixel_format=frame.format.name,decode_fps=(len(arrivals)-1)/(arrivals[-1]-arrivals[0]) if len(arrivals)>1 else 0,frames=count)
        except Exception as e:
            with lock:states[kind]=dict(error=type(e).__name__)
            stop.wait(.5)
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_):pass
    def do_GET(self):
        if self.path=='/':return self.send(PAGE.encode(),'text/html; charset=utf-8')
        if self.path=='/status.json':
            with lock:
                status={kind:dict(states.get(kind,{}),live=kind in frames and time.perf_counter()-frames[kind][1]<2) for kind in ['gray','depth']}
            return self.send(json.dumps(status).encode(),'application/json')
        kind=self.path.lstrip('/').split('.')[0]
        if kind not in ['gray','depth']:self.send_error(404);return
        if self.path.endswith('.jpg'):
            with lock:frame=frames.get(kind)
            if not frame or time.perf_counter()-frame[1]>2:self.send_error(503);return
            return self.send(frame[2],'image/jpeg')
        if not self.path.endswith('.mjpg'):self.send_error(404);return
        self.send_response(200);self.send_header('Content-Type','multipart/x-mixed-replace; boundary=frame');self.end_headers();previous=0
        try:
            while not stop.is_set():
                with lock:frame=frames.get(kind)
                if frame and frame[0]!=previous and time.perf_counter()-frame[1]<2:
                    previous=frame[0];data=frame[2];self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: '+str(len(data)).encode()+b'\r\n\r\n'+data+b'\r\n')
                stop.wait(.02)
        except (BrokenPipeError,ConnectionResetError):pass
    def send(self,data,mime):
        self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
for sig in [signal.SIGINT,signal.SIGTERM]:signal.signal(sig,lambda *_:stop.set())
server=ThreadingHTTPServer(('127.0.0.1',8765),Handler);server.daemon_threads=True;server.timeout=.25
workers=[threading.Thread(target=decoder,args=args) for args in [('gray',8554,'stereo'),('depth',8554,'depth')]]
for worker in workers:worker.start()
print('http://127.0.0.1:8765/',flush=True)
try:
    while not stop.is_set() and not (ROOT/'STOP-VIEWER').exists():server.handle_request()
finally:
    stop.set();server.server_close()
    for worker in workers:worker.join(timeout=10)
