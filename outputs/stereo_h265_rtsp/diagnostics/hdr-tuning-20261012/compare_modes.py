"""Compare unmodified decoded luma at equal AE targets; restore user settings."""
import json
import sys
import subprocess
import time
from pathlib import Path
import gi
import numpy as np
import yaml
from PIL import Image
from noise_analysis import analyze_patch
gi.require_version('Gst', '1.0')
gi.require_version('GstApp', '1.0')
gi.require_version('GstVideo', '1.0')
from gi.repository import Gst, GstApp, GstVideo
Gst.init(None)
OUT=Path('/home/ubuntu/hdr-tuning-20261012')/(sys.argv[1] if len(sys.argv)>1 else 'equal-target-baseline')
OUT.mkdir(exist_ok=True)
def run(*args):
    process=subprocess.run(args,text=True,capture_output=True,timeout=50)
    if process.returncode and args[0]=='sc132gs-camera' and args[1]=='apply':
        log=Path('/run/sc132gs-camera-server.log').read_text()
        if 'input STREAMON: Cannot allocate memory' in log:
            (OUT/f'codec-failure-{time.time_ns()}.log').write_text(log)
            subprocess.run(['systemctl','stop','sc132gs-camera-rtsp'],check=True)
            if subprocess.run(['fuser','/dev/video32','/dev/video33'],capture_output=True).returncode==0:
                raise RuntimeError('Encoder still owned; recovery aborted')
            subprocess.run(['modprobe','-r','iris_vpu'],check=True)
            subprocess.run(['modprobe','iris_vpu'],check=True)
            subprocess.run(['/usr/bin/python3','/home/ubuntu/stereo-h265-rtsp/camera_platform.py','restore'],check=True)
            process=subprocess.run(args,text=True,capture_output=True,timeout=50)
    if process.returncode:
        (OUT/f'command-failure-{time.time_ns()}.json').write_text(json.dumps(dict(args=args,code=process.returncode,stdout=process.stdout,stderr=process.stderr)))
    process.check_returncode()
    return process.stdout.strip()
saved=yaml.safe_load(Path('/var/lib/sc132gs-camera/settings.yaml').read_text())
(OUT/'before-settings.yaml').write_text(yaml.safe_dump(saved))
def capture(name):
    pipe=Gst.parse_launch('rtspsrc location=rtsp://192.168.137.226:8554/stereo protocols=tcp latency=100 ! rtph265depay ! h265parse ! avdec_h265 ! appsink name=frames sync=false max-buffers=2 drop=true')
    sink=pipe.get_by_name('frames')
    pipe.set_state(Gst.State.PLAYING)
    frames=[]
    try:
        for index in range(100):
            error=pipe.get_bus().pop_filtered(Gst.MessageType.ERROR)
            if error: raise RuntimeError(error.parse_error())
            sample=sink.try_pull_sample(500*Gst.MSECOND)
            if sample is None: continue
            if index<35: continue
            info=GstVideo.VideoInfo.new_from_caps(sample.get_caps())
            fmt=sample.get_caps().get_structure(0).get_value('format')
            data=sample.get_buffer().extract_dup(0,sample.get_buffer().get_size())
            if fmt=='I420_10LE': dtype,scale='<u2',1
            elif fmt=='I420': dtype,scale='u1',1023/255
            else: raise RuntimeError(fmt)
            pixels=np.ndarray((info.height,info.width),dtype=dtype,buffer=data,offset=info.offset[0],strides=(info.stride[0],np.dtype(dtype).itemsize)).copy().astype(float)*scale
            frames.append(pixels)
            if len(frames)<(12 if len(sys.argv)>3 and sys.argv[3]=='noise' else 1): continue
            stack=np.stack(frames)
            pixels=stack.mean(axis=0)
            np.save(OUT/(name+'.npy'),pixels)
            Image.fromarray(np.rint(pixels*255/1023).clip(0,255).astype('uint8')).save(OUT/(name+'.png'))
            eyes=[]
            for eye in np.hsplit(pixels,2):
                h,w=eye.shape
                roi=eye[h//10:h*9//10,w//10:w*9//10]
                eyes.append(dict(mean=float(roi.mean()),percentiles={str(p):float(np.percentile(roi,p)) for p in (1,10,40,50,90,99)},clipped_percent=float(np.mean(roi>=1020)*100)))
            dark=[]
            # Fixed background patches, excluding the moving person and lamps.
            patch_data={}
            for eye in range(2):
                for patch_index,box in enumerate(((30,80,160,220),(500,470,660,620))):
                    x0,y0,x1,y1=box
                    offset=eye*info.width//2
                    data=stack[:,y0:y1,offset+x0:offset+x1]
                    if len(frames)>1:
                        metrics=analyze_patch(data)
                    else:
                        metrics=dict(mean=float(data.mean()))
                    dark.append(dict(eye=eye,box=box,**metrics))
                    patch_data[f'eye{eye}_patch{patch_index}']=data.astype(np.float32)
            np.savez_compressed(OUT/(name+'-patch-frames.npz'),**patch_data)
            return dict(caps=sample.get_caps().to_string(),eyes=eyes,frames=len(frames),dark_patches=dark)
        raise TimeoutError('decoded frame')
    finally: pipe.set_state(Gst.State.NULL)
def main():
    records=[]
    try:
        for target in (tuple(map(int,sys.argv[2].split(','))) if len(sys.argv)>2 else (10,20,40)):
            for mode in ('linear','hdr'):
                native_target=target
                requested_fps=30
                if mode=='hdr' and len(sys.argv)>4 and sys.argv[4] in ('hdr15','hdr20','hdr24'):
                    requested_fps=int(sys.argv[4][3:])
                if len(sys.argv)>4 and sys.argv[4]=='black':
                    black=37 if mode=='linear' else 53
                    native_target=round(100*(black+(1023-black)*target/100)/1023)
                maximum_time=16000 if mode=='linear' and len(sys.argv)>5 and sys.argv[5]=='cap16' else 0
                reply=run('sc132gs-camera','apply','--mode',mode,'--max-fps',str(requested_fps),'--ae','on','--ae-target',str(native_target),'--max-exposure-us',str(maximum_time))
                time.sleep(20)
                name=f'{mode}-{target}'
                result=dict(mode=mode,target=target,native_target=native_target,requested_fps=requested_fps,reply=reply,status=run('sc132gs-ctl','status'),decoded=capture(name))
                records.append(result)
                (OUT/'comparison.json').write_text(json.dumps(records,indent=2))
                print(json.dumps(result),flush=True)
    finally:
        print(run('sc132gs-camera','apply','--mode',saved['mode'],'--max-fps',str(saved['max_fps']),'--ae','on' if saved['ae'] else 'off','--ae-target',str(saved['brightness']),'--max-gain-index',str(saved['max_gain_index']),'--max-exposure-us',str(saved['max_exposure_us'])),flush=True)

if __name__=='__main__': main()
