"""Use the frozen offline pair for a bounded, camera-independent GPU benchmark."""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import argparse

import cv2
import numpy as np

from run import ROOT, remote

parser = argparse.ArgumentParser()
parser.add_argument('--label', default='wide')
parser.add_argument('--reference', action='store_true')
parser.add_argument('--mode', choices=['reference', 'tiled', 'sliding', 'spatial', 'packed', 'vector', 'reuse', 'ring', 'wide'], default='wide')
parser.add_argument('--case', choices=['photo', 'shifted', 'textureless'], default='photo')
parser.add_argument('--iterations', type=int, default=30)
parser.add_argument('--gpu-rectify', action='store_true', help='Full-resolution mirrored stereo -> half-size rectification on GPU')
parser.add_argument('--fixed-remap', action='store_true', help='Explicit OpenCV fixed-coordinate CPU reference for GPU interpolation')
parser.add_argument('--rectification-case', choices=['photo','borders'],default='photo')
args = parser.parse_args()
assert args.label.replace('-', '').replace('_', '').isalnum()
output = ROOT / args.label
output.mkdir(exist_ok=True)

spec = importlib.util.spec_from_file_location('live_depth', ROOT.parent/'live-depth/server.py')
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
calibration = ROOT.parent/'calibration-ready-20261014/geometry-analysis/stereo-candidate.npz'
snapshot = ROOT.parent/'calibration-ready-20261014/rtsp-decode-stable/decoded.png'
processor = module.StereoDepth(calibration)
image = cv2.imread(str(snapshot), 0)
if args.rectification_case=='borders':
    assert args.gpu_rectify
    rows,cols=np.indices(image.shape)
    image=((rows*17+cols*3)%256).astype(np.uint8)
eyes = (cv2.flip(image[:, 1088:], 1), cv2.flip(image[:, :1088], 1))
rectified = [cv2.remap(im, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
             for im, (mx, my) in zip(eyes, processor.maps)]
map_files={}
interpolation_difference=[]
if args.gpu_rectify or args.fixed_remap:
    assert args.case=='photo'
    for eye,(mx,my) in enumerate(processor.maps):
        integer,fraction=cv2.convertMaps(mx,my,cv2.CV_16SC2)
        if args.rectification_case=='borders':
            positions=[(x,y) for x in (-33,-32,-31,-1,0,1,15,16,31,32,1087*32,1087*32+31,1088*32)
                       for y in (-33,-1,0,1,15,16,31,1279*32,1279*32+31,1280*32)]
            for i,(qx,qy) in enumerate(positions):
                py,px=divmod(i,544)
                integer[py,px]=(qx//32,qy//32)
                fraction[py,px]=((qy&31)<<5)|(qx&31)
        fixed=cv2.remap(eyes[eye],integer,fraction,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)
        delta=np.abs(rectified[eye].astype(np.int16)-fixed.astype(np.int16))
        interpolation_difference.append(dict(differing_pixels=int((delta>0).sum()),maximum_gray_difference=int(delta.max())))
        rectified[eye]=fixed
        quantized=integer.astype(np.int32)*32
        quantized[:,:,0]+=(fraction&31).astype(np.int32)
        quantized[:,:,1]+=(fraction>>5).astype(np.int32)
        map_files[('left' if eye==0 else 'right')+'-map.i32']=quantized.astype('<i4').tobytes()
if args.case == 'shifted':
    rectified[0] = np.random.default_rng(20261015).integers(0, 256, (640,544), dtype=np.uint8)
    rectified[1] = np.zeros((640,544), np.uint8)
    rectified[1][:,:-12] = rectified[0][:,12:]
elif args.case == 'textureless':
    rectified = [np.zeros((640,544),np.uint8),np.zeros((640,544),np.uint8)]
files = {'stereo_bench.cpp': (ROOT/'stereo_bench.cpp').read_bytes(),
         'left.u8': rectified[0].tobytes(), 'right.u8': rectified[1].tobytes()}
if args.gpu_rectify:
    assert args.case=='photo', 'GPU rectification uses the fixed physical stereo snapshot'
    files['source.u8']=image.tobytes()
    files.update(map_files)
payload = {key: base64.b64encode(value).decode() for key, value in files.items()}
job = '''
import base64,json,pathlib,subprocess
root=pathlib.Path('/home/ubuntu/opencl-depth-20261015')
root.mkdir(exist_ok=True)
def board_state():
    service=subprocess.run(['systemctl','show','sc132gs-camera-rtsp','-p','ActiveState','-p','MainPID'],capture_output=True,text=True,check=True).stdout.strip()
    settings=subprocess.run(['sudo','-n','sha256sum','/var/lib/sc132gs-camera/settings.yaml'],capture_output=True,text=True,check=True).stdout.strip()
    return dict(service=service,settings_hash=settings)
before=board_state()
for name,data in payload.items():
    (root/name).write_bytes(base64.b64decode(data))
build=subprocess.run(['g++','-std=c++17','-O3','stereo_bench.cpp','-lOpenCL','-o','stereo_bench'],cwd=root,capture_output=True,text=True,timeout=30)
if build.returncode: raise RuntimeError(build.stderr)
run=subprocess.run(['./stereo_bench']+run_args,cwd=root,capture_output=True,text=True,timeout=120)
if run.returncode: raise RuntimeError(run.stderr+run.stdout)
after=board_state()
print(json.dumps(dict(stdout=run.stdout,stderr=run.stderr,board_before=before,board_after=after,
    rectified={name:base64.b64encode((root/name).read_bytes()).decode() for name in ('rectified-left.u8','rectified-right.u8')} if '--gpu-rectify' in run_args else {},
    disparity=base64.b64encode((root/'disparity.f32').read_bytes()).decode())))
'''
run_args=['--reference' if args.reference else '--'+args.mode, str(args.iterations)]
if args.gpu_rectify:run_args.append('--gpu-rectify')
result = json.loads(remote('python3 -', ('payload='+repr(payload)+'\nrun_args='+repr(run_args)+'\n'+job).encode(), timeout=160))
raw = base64.b64decode(result.pop('disparity'))
(output/'disparity.f32').write_bytes(raw)
(output/'stereo_bench.cpp').write_bytes(files['stereo_bench.cpp'])
for name,data in result['rectified'].items():
    pixels=np.frombuffer(base64.b64decode(data),np.uint8).reshape(640,544)
    eye=0 if 'left' in name else 1
    assert np.array_equal(pixels,rectified[eye])
    cv2.imwrite(str(output/name.replace('.u8','.png')),pixels)
disparity = np.frombuffer(raw, np.float32).reshape(640, 544).copy()
valid = np.isfinite(disparity) & (disparity > 0)
yy, xx = np.indices(disparity.shape)
xi = np.clip(np.rint(xx-np.nan_to_num(disparity, nan=0)).astype(np.int32), 0, 543)
valid &= processor.supports[0] & processor.supports[1][yy, xi]
depth = np.where(valid, (1/processor.q[3, 2])*processor.q[2, 3]/disparity, np.nan).astype(np.float32)
np.save(output/'depth-m.npy', depth, allow_pickle=False)
cv2.imwrite(str(output/'valid-mask.png'), valid.astype(np.uint8)*255)
index = np.rint((1-np.clip((np.nan_to_num(depth,nan=3)-.2)/2.8,0,1))*255).astype(np.uint8)
color = cv2.applyColorMap(index, cv2.COLORMAP_TURBO)
color[~valid] = 0
canvas = np.full((730, 1088, 3), 22, np.uint8)
canvas[40:680,:544] = cv2.cvtColor(rectified[0],cv2.COLOR_GRAY2BGR)
canvas[40:680,544:] = color
for text, xy in [('RECTIFIED LEFT', (16,27)), ('ADRENO OPENCL CENSUS BM', (560,27)),
                 ('Experimental BM, not SGBM | No hole filling | Accuracy unverified', (16,708))]:
    cv2.putText(canvas,text,xy,0,.55,(240,240,240),1,cv2.LINE_AA)
cv2.imwrite(str(output/'gpu-preview.png'),canvas)
metrics = dict(line.split('=',1) for line in result['stdout'].splitlines() if '=' in line)
report = dict(algorithm='5x5 census + 5x5 box Hamming cost, integer WTA, uniqueness10, bidirectional LR<=1px; NOT SGM/SGBM',
              gpu_metrics=metrics, final_valid_fraction=float(valid.mean()), resolution=[544,640], disparities=128,
              calibration_sha256=processor.calibration_sha256,
              snapshot_sha256=hashlib.sha256(snapshot.read_bytes()).hexdigest() if args.case=='photo' and args.rectification_case=='photo' else None,
              test_case=args.case,rectification_case=args.rectification_case,
              board_before=result['board_before'],board_after=result['board_after'],
              camera_state_same_during_this_run=result['board_before']==result['board_after'],
              camera_active_before_and_after=all('ActiveState=active' in result[key]['service'] for key in ('board_before','board_after')),
              host_to_gpu_and_disparity_readback_in_wall_time=True,
              gpu_rectification_in_wall_time=args.gpu_rectify, metric_conversion_in_wall_time=False,
              interpolation='OpenCV INTER_LINEAR compatible 1/32 pixel quantized bilinear, BORDER_CONSTANT=0',
              difference_from_previous_float_map_CPU_path=interpolation_difference,
              full_resolution_source_size=[2176,1280] if args.gpu_rectify else None,
              maps_uploaded_once_outside_frame_timing=args.gpu_rectify,
              live_stream_acceleration_verified=False, metric_accuracy_verified=False,
              transfer_to_board_via_ssh_in_wall_time=False,
              kernel_input_hashes={name:hashlib.sha256(value).hexdigest() for name,value in files.items()},
              note='Repeated frozen image, streaming service kept active; different algorithm from CPU SGBM, not an equivalent quality speedup.')
reference_path=ROOT/('disparity-rectified-fixed-reference.f32' if args.gpu_rectify or args.fixed_remap else 'disparity-coalesced.f32' if args.case=='photo' else args.case+'-reference.f32')
if args.rectification_case=='borders':reference_path=ROOT/'border-disparity-reference-not-provided.f32'
if (args.case!='photo' or args.fixed_remap) and (args.reference or args.mode=='reference'):
    reference_path.write_bytes(raw)
if reference_path.exists():
    reference=np.frombuffer(reference_path.read_bytes(),np.float32).reshape(640,544)
    report['whole_image_disparity_equal_to_previous']=bool(np.array_equal(reference,disparity,equal_nan=True))
    assert report['whole_image_disparity_equal_to_previous'], 'Changed disparity output; preserve failed trial for diagnosis'
if args.case=='textureless':
    assert not np.isfinite(disparity).any(), 'Textureless input invented depth'
    report['textureless_all_invalid_passed']=True
if args.case=='shifted':
    interior=disparity[16:-16,32:-32]
    assert np.isfinite(interior).mean()>.99 and np.all(interior[np.isfinite(interior)]==12)
    report['known_12px_shift_passed']=True
(output/'benchmark.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,indent=2))
