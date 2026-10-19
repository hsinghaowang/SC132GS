"""Stage an overlay of the exact deployed Main10 sources; never stop/change an owner."""
from pathlib import Path
import base64,difflib,hashlib,json,struct,subprocess
import cv2,numpy as np

HERE=Path(__file__).resolve().parent
OUT=HERE/'rectification-evidence-20261016'
BOARD='/home/ubuntu/main10-rectification-20261016'
SSH=['ssh','-o','BatchMode=yes','-o','ConnectTimeout=6','ubuntu@192.168.137.226']
def remote(code,timeout=120):
    p=subprocess.run(SSH+['python3 -'],input=code.encode(),capture_output=True,timeout=timeout)
    if p.returncode:raise RuntimeError(p.stdout.decode(errors='replace')+p.stderr.decode(errors='replace'))
    return p.stdout
def replace(text,old,new):
    if text.count(old)!=1:raise RuntimeError('baseline anchor is not unique: '+old[:80])
    return text.replace(old,new)
def between(text,start,end):return text[text.index(start):text.index(end,text.index(start))]
def fixtures():
    out=OUT/'fixtures';out.mkdir(parents=True,exist_ok=True)
    candidate=HERE.parent/'slam_benchmark/calibration-ready-20261014/geometry-analysis/stereo-candidate.npz'
    c=np.load(candidate);sha=hashlib.sha256(candidate.read_bytes()).digest()
    r=c['R_cam1_cam0'].T;t=-r@c['T_cam1_cam0_m_assuming_20mm_squares']
    rl,rr,pl,pr,q=cv2.fisheye.stereoRectify(c['K1'],c['D1'],c['K0'],c['D0'],(1088,1280),r,t,flags=cv2.CALIB_ZERO_DISPARITY,newImageSize=(1088,1280),balance=0.)
    maps=[]
    for k,d,rect,p in [(c['K1'],c['D1'],rl,pl),(c['K0'],c['D0'],rr,pr)]:
        mx,my=cv2.fisheye.initUndistortRectifyMap(k,d,rect,p,(1088,1280),cv2.CV_32FC1)
        a,b=cv2.convertMaps(mx,my,cv2.CV_16SC2);xy=a.astype(np.int32)*32;xy[:,:,0]+=b&31;xy[:,:,1]+=b>>5;maps.append(xy)
    header=struct.pack('<8s9I32s',b'S132RMAP',1,1088,1280,1088,1280,1,0,32,10,sha)
    yy,xx=np.indices((1280,1088));a=((xx*7+yy*11)%1024).astype('<u2');b=((xx*13+yy*5+123)%1024).astype('<u2')
    a.tofile(out/'cam0.u16');b.tofile(out/'cam1.u16')
    identity=np.stack([xx*32,yy*32],axis=2).astype('<i4')
    for name,xy in [('identity',[identity,identity]),('calibration',maps)]:
        (out/(name+'.map')).write_bytes(header+b''.join(m.astype('<i4').tobytes() for m in xy))
        images=[]
        for image,m in zip([b,a],xy):
            integer=(m>>5).astype(np.int16);fraction=((m[:,:,0]&31)|((m[:,:,1]&31)<<5)).astype(np.uint16)
            images.append(cv2.remap(image,integer,fraction,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT))
        np.concatenate(images,axis=1).astype('<u2').tofile(out/(name+'-expected.u16'))
    (out/'invalid.map').write_bytes(header[:40])
    return out
def overlay(baseline):
    out=OUT/'overlay';out.mkdir(parents=True,exist_ok=True)
    current=(HERE/'StereoRtspServer.cpp').read_text();text=baseline['StereoRtspServer.cpp']
    text=replace(text,'#include "SensorSignalCalibration.hpp"','#include "SensorSignalCalibration.hpp"\n#include "GpuStereoRectifier.hpp"\n#include "DepthPipeline.hpp"\n#include "DepthRtspEndpoint.hpp"\n#include "StereoOutputWorker.hpp"')
    text=replace(text,'    Settings settings;','    Settings settings;\n    detail::DepthRtspEndpoint depth_endpoint;')
    validation=between(current,'        if ((!settings.gpu_rectification_map','        const bool experimental')
    text=replace(text,'    std::variant<std::monostate, Error> run() {','    std::variant<std::monostate, Error> run() {\n'+validation.rstrip())
    text=replace(text,'        gst_object_unref(mounts);','        if(!settings.depth_calibration.empty())depth_endpoint.mount(mounts);\n        gst_object_unref(mounts);')
    extra=between(current,'        if(!linear_display &&','        if(settings.main10 &&')
    text=replace(text,'        const bool linear_display = !exposure.snapshot().hdr_enabled;','        const bool linear_display = !exposure.snapshot().hdr_enabled;\n'+extra.rstrip())
    extra=between(current,'        std::unique_ptr<detail::GpuStereoRectifier>','        // Prepare the consumer')
    text=replace(text,'        // Prepare the consumer before STREAMON:',''+extra+'        // Prepare the consumer before STREAMON:')
    extra=between(current,'            // Depth receives','            ++input_pairs;')
    text=replace(text,'            ++input_pairs;',extra+'            ++input_pairs;')
    extra=between(current,'            if(stereo_worker) {','            } else if (settings.main10) {')
    text=replace(text,'            if (settings.main10) {',extra+'            } else if (settings.main10) {')
    extra=between(current,'                if(stereo_worker){const auto s=','                const auto encoded =')
    text=replace(text,'            if (seconds >= 5.0) {','            if (seconds >= 5.0) {\n'+extra.rstrip())
    extra=between(current,'                if(rectifier) {\n                    const auto ae=','                if (binning60) {')
    text=replace(text,'                if (binning60) {',extra+'                if (binning60) {')
    extra=between(current,'        if(depth)depth->stop();','    }\n};')
    text=replace(text,'        }\n    }\n};','        }\n'+extra+'    }\n};')
    (out/'StereoRtspServer.cpp').write_text(text)
    text=replace(baseline['StereoRtspServer.hpp'],'    int bitrate{20000000};','    std::string gpu_rectification_map;\n    std::string depth_calibration;\n    int bitrate{20000000};')
    (out/'StereoRtspServer.hpp').write_text(text)
    text=replace(baseline['main.cpp'],'            else if (option == "--bitrate") settings.bitrate = positive_int(value);','            else if (option == "--bitrate") settings.bitrate = positive_int(value);\n            else if (option == "--gpu-rectification-map") settings.gpu_rectification_map=value;\n            else if (option == "--depth-calibration") settings.depth_calibration=value;')
    (out/'main.cpp').write_text(text)
    additions='''
find_package(OpenCL REQUIRED)
add_library(stereo_gpu_rectification GpuStereoRectifier.cpp StereoOutputWorker.cpp)
target_compile_features(stereo_gpu_rectification PUBLIC cxx_std_17 PRIVATE cxx_std_20)
target_link_libraries(stereo_gpu_rectification PRIVATE OpenCL::OpenCL Threads::Threads)
target_include_directories(stereo_gpu_rectification PRIVATE "${SC132GS_AE_SOURCE_DIR}")
add_library(stereo_depth_pipeline DepthPipeline.cpp depth/GpuStereoDepth.cpp)
target_compile_features(stereo_depth_pipeline PUBLIC cxx_std_17 PRIVATE cxx_std_20)
target_link_libraries(stereo_depth_pipeline PRIVATE OpenCL::OpenCL Threads::Threads PkgConfig::GST)
target_link_libraries(stereo-h265-rtsp PRIVATE stereo_gpu_rectification stereo_depth_pipeline)
'''
    tests='''
if(BUILD_TESTING)
add_executable(gpu-stereo-rectifier-check GpuStereoRectifierCheck.cpp)
target_compile_features(gpu-stereo-rectifier-check PRIVATE cxx_std_17)
target_link_libraries(gpu-stereo-rectifier-check PRIVATE stereo_gpu_rectification)
add_executable(depth-pipeline-check DepthPipelineCheck.cpp)
target_compile_features(depth-pipeline-check PRIVATE cxx_std_17)
target_link_libraries(depth-pipeline-check PRIVATE stereo_depth_pipeline)
add_test(NAME depth-pipeline-failure-isolation COMMAND depth-pipeline-check)
endif()
'''
    (out/'CMakeLists.txt').write_text(replace(baseline['CMakeLists.txt'],'include(CTest)',additions+'\ninclude(CTest)')+tests)
    for name in ['GpuStereoRectifier.hpp','GpuStereoRectifier.cpp','GpuStereoRectifierCheck.cpp','StereoOutputWorker.hpp','StereoOutputWorker.cpp','DepthPipeline.hpp','DepthPipeline.cpp','DepthPipelineCheck.cpp','DepthRtspEndpoint.hpp','depth/GpuStereoDepth.hpp','depth/GpuStereoDepth.cpp','depth/stereo_kernels.hpp']:
        dest=out/name;dest.parent.mkdir(exist_ok=True,parents=True);dest.write_bytes((HERE/name).read_bytes())
    diff=''
    for name in baseline:
        diff+=''.join(difflib.unified_diff(baseline[name].splitlines(True),(out/name).read_text().splitlines(True),fromfile='deployed/'+name,tofile='new/'+name))
    (OUT/'production-overlay.diff').write_text(diff)
    return out
def main():
    OUT.mkdir(exist_ok=True)
    data=json.loads(remote('''from pathlib import Path
import json,hashlib
root=Path('/home/ubuntu/sc132gs-kernel-sync-20261014')
deployed=Path('/home/ubuntu/stereo-h265-rtsp/build-main10/stereo-h265-rtsp')
assert hashlib.sha256(deployed.read_bytes()).digest()==hashlib.sha256((root/'userspace-build/stereo-h265-rtsp').read_bytes()).digest()
names=['StereoRtspServer.cpp','StereoRtspServer.hpp','main.cpp','CMakeLists.txt']
print(json.dumps(dict(binary_sha256=hashlib.sha256(deployed.read_bytes()).hexdigest(),files={n:(root/'userspace'/n).read_text() for n in names})))
'''))
    (OUT/'baseline.json').write_text(json.dumps(data,indent=2))
    sources=overlay(data['files']);fixture=fixtures()
    paths={p.relative_to(sources).as_posix():'source/'+p.relative_to(sources).as_posix() for p in sources.rglob('*') if p.is_file()}
    payload={'source/'+name:base64.b64encode((sources/name).read_bytes()).decode() for name in paths}
    payload.update({'fixtures/'+p.name:base64.b64encode(p.read_bytes()).decode() for p in fixture.iterdir() if p.is_file()})
    old=HERE.parent/'slam_benchmark/board-live-depth'
    for name in ['left-map.i32','right-map.i32','left-valid.u8','right-valid.u8','palette.u8','focal-baseline.txt','parameters.json']:
        payload['depth-calibration/'+name]=base64.b64encode((old/name).read_bytes()).decode()
    script='''from pathlib import Path
import base64,hashlib,json,shutil,subprocess
root=Path(BOARD);root.mkdir(exist_ok=True)
base=Path('/home/ubuntu/sc132gs-kernel-sync-20261014')
if not (root/'source').exists():shutil.copytree(base/'userspace',root/'source')
if not (root/'ae').exists():shutil.copytree(base/'ae',root/'ae')
for name,content in PAYLOAD.items():
    p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(base64.b64decode(content))
commands=[['cmake','-S',str(root/'source'),'-B',str(root/'build'),'-DCMAKE_BUILD_TYPE=Release','-DSC132GS_AE_SOURCE_DIR='+str(root/'ae'),'-DBUILD_TESTING=ON'],['cmake','--build',str(root/'build'),'--target','stereo-h265-rtsp','gpu-stereo-rectifier-check','depth-pipeline-check','-j','3'],['ctest','--test-dir',str(root/'build'),'-R','depth-pipeline-failure-isolation','--output-on-failure']]
log=''
for cmd in commands:
    p=subprocess.run(['taskset','--cpu-list','1-6']+cmd,capture_output=True,text=True);log+=p.stdout+p.stderr
    (root/'build.log').write_text(log)
    if p.returncode:print(log);raise SystemExit(p.returncode)
print(log)
manifest={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'source').rglob('*') if p.is_file()}
(root/'manifest.json').write_text(json.dumps(manifest,indent=2))
print('STAGED_BINARY_SHA256',hashlib.sha256((root/'build/stereo-h265-rtsp').read_bytes()).hexdigest())
'''.replace('BOARD',repr(BOARD)).replace('PAYLOAD',repr(payload))
    result=remote(script,240);(OUT/'build.log').write_bytes(result);print(result.decode())
if __name__=='__main__':main()
