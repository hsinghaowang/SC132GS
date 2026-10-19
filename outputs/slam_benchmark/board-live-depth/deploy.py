"""Generate maps without modifying calibration; freeze and build the board consumer."""
from pathlib import Path
import base64
import hashlib
import json
import re
import subprocess
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parent
SSH=['ssh','-o','BatchMode=yes','-o','ConnectTimeout=6','ubuntu@192.168.137.226']
BOARD='/home/ubuntu/board-live-depth-20261015'

def remote(source,timeout=90):
    p=subprocess.run(SSH+['python3 -'],input=source.encode(),capture_output=True,timeout=timeout)
    if p.returncode:raise RuntimeError(p.stdout.decode(errors='replace')+p.stderr.decode(errors='replace'))
    return p.stdout

def maps():
    path=ROOT.parent/'calibration-ready-20261014/geometry-analysis/stereo-candidate.npz'
    data=np.load(path)
    k0,d0,k1,d1=[data[k] for k in ['K0','D0','K1','D1']]
    r=data['R_cam1_cam0'].T;t=-r@data['T_cam1_cam0_m_assuming_20mm_squares']
    metadata={'calibration_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'cam0':'physical_right_native_unmirrored','cam1':'physical_left_native_unmirrored','binning':False,'depth_size':[544,640],'gray_size':[2176,1280],'disparity_search_count':96,'depth_units':'meter_optical_axis_Z','color_range_m':[0.2,3.0],'checker_square_assumption_mm':20}
    metadata['gray_order']='cam1_left_then_cam0_right'
    metadata['gray_codec']='HEVC Main 8bit NV12 preview'
    metadata['exposure_control']='native capture prototype, no AE controller'
    metadata['physical_side_verified_by_cover_test']=False
    metadata['camera_side_evidence']='inferred from native unmirrored calibration extrinsics'
    metadata['cam1_center_in_cam0_m']=(-data['R_cam1_cam0'].T@data['T_cam1_cam0_m_assuming_20mm_squares']).tolist()
    for prefix,size in [('',(544,640)),('full-',(1088,1280))]:
        rl,rr,pl,pr,q=cv2.fisheye.stereoRectify(k1,d1,k0,d0,(1088,1280),r,t,flags=cv2.CALIB_ZERO_DISPARITY,newImageSize=size,balance=0.0)
        if not prefix:
            fb=float(q[2,3]/q[3,2]);assert fb>0
            (ROOT/'focal-baseline.txt').write_text(f'{fb:.12g}\n')
            metadata.update(focal_times_baseline_m_px=fb,Q=q.tolist())
        for name,k,d,rect,p in [('left',k1,d1,rl,pl),('right',k0,d0,rr,pr)]:
            mx,my=cv2.fisheye.initUndistortRectifyMap(k,d,rect,p,size,cv2.CV_32FC1)
            integer,fraction=cv2.convertMaps(mx,my,cv2.CV_16SC2)
            xy=integer.astype(np.int32)*32;xy[:,:,0]+=fraction&31;xy[:,:,1]+=fraction>>5
            xy.astype('<i4').tofile(ROOT/f'{prefix}{name}-map.i32')
            if not prefix:
                valid=((mx>=1)&(mx<1086)&(my>=1)&(my<1278)).astype(np.uint8)
                cv2.erode(valid,np.ones((5,5),np.uint8)).tofile(ROOT/f'{name}-valid.u8')
    bgr=cv2.applyColorMap(np.arange(255,-1,-1,dtype=np.uint8).reshape(256,1),cv2.COLORMAP_TURBO).reshape(256,3).astype(float)/255
    b,g,r=bgr.T;y=.2126*r+.7152*g+.0722*b
    palette=np.stack([16+219*y,128+224*(b-y)/1.8556,128+224*(r-y)/1.5748,np.zeros(256)],axis=1)
    np.clip(np.rint(palette),0,255).astype(np.uint8).tofile(ROOT/'palette.u8')
    (ROOT/'parameters.json').write_text(json.dumps(metadata,indent=2)+'\n')

def deploy():
    maps()
    original=(ROOT.parent/'opencl-depth-20261015/stereo_bench.cpp').read_text()
    source=re.search(r'const char\* source = R"CLC\((.*?)\)CLC";',original,re.S).group(1)
    source=source.replace('#define D 128','#define D 96')
    (ROOT/'stereo_kernels.hpp').write_text('#pragma once\ninline const char* stereo_kernels=R"CLC('+source+')CLC";\n')
    names=['GpuStereoDepth.hpp','GpuStereoDepth.cpp','VideoStream.hpp','VideoStream.cpp','main.cpp','stereo_kernels.hpp','parameters.json','focal-baseline.txt','left-map.i32','right-map.i32','left-valid.u8','right-valid.u8','full-left-map.i32','full-right-map.i32','palette.u8']
    payload={name:base64.b64encode((ROOT/name).read_bytes()).decode() for name in names}
    script='''from pathlib import Path
import base64,hashlib,subprocess,shlex,shutil
root=Path(BOARD);root.mkdir(exist_ok=True)
for name,data in PAYLOAD.items():(root/name).write_bytes(base64.b64decode(data))
api=Path('/home/ubuntu/capture-api-20261015')
header=api/'outputs/gs130wi_capture/include/gs130wi/Capture.hpp'
assert hashlib.sha256(header.read_bytes()).hexdigest()=='58cc08e615559388fe26cdad020640baa7f3d298effc961bb9396e797abc58ca'
(root/'include/gs130wi').mkdir(parents=True,exist_ok=True)
shutil.copyfile(header,root/'include/gs130wi/Capture.hpp')
assert hashlib.sha256((api/'build/libgs130wi_capture.a').read_bytes()).hexdigest()=='076a34d35ac34094ee2810907003d6bb3bde2c36fba6d6faeb0287e48cbbe856'
shutil.copyfile(api/'build/libgs130wi_capture.a',root/'libgs130wi_capture.a')
flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','gstreamer-1.0','gstreamer-app-1.0','gstreamer-rtsp-server-1.0','gstreamer-video-1.0'],text=True))
cmd=['g++','-std=c++17','-O3','-DNDEBUG','-Wall','-Wextra','-Iinclude','main.cpp','GpuStereoDepth.cpp','VideoStream.cpp','libgs130wi_capture.a','-lOpenCL','-pthread','-o','board-live-depth']+flags
p=subprocess.run(cmd,cwd=root,capture_output=True,text=True)
(root/'build.log').write_text(p.stdout+p.stderr);print(p.stdout+p.stderr)
if p.returncode:raise SystemExit(p.returncode)
print('BUILD_OK',hashlib.sha256((root/'board-live-depth').read_bytes()).hexdigest())
'''.replace('BOARD',repr(BOARD)).replace('PAYLOAD',repr(payload))
    result=remote(script,180);(ROOT/'build.log').write_bytes(result);print(result.decode())

if __name__=='__main__':deploy()
