"""Independent CPU replay of native remap, Census BM, metric mask, and timing CSVs."""
from pathlib import Path
import json,sys
import cv2,numpy as np
ROOT=Path(__file__).resolve().parent
W,H,D=544,640,96
INVALID=np.uint32(0xffffffff)

def remap(raw,map_path,size):
    xy=np.fromfile(map_path,'<i4').reshape(size[1],size[0],2)
    x,y=xy[:,:,0]>>5,xy[:,:,1]>>5;fx,fy=xy[:,:,0]&31,xy[:,:,1]&31
    def sample(dx,dy):
        xx,yy=x+dx,y+dy;ok=(xx>=0)&(xx<1088)&(yy>=0)&(yy<1280)
        return np.where(ok,raw[np.clip(yy,0,1279),np.clip(xx,0,1087)],0).astype(np.int32)
    total=sample(0,0)*(32-fx)*(32-fy)+sample(1,0)*fx*(32-fy)+sample(0,1)*(32-fx)*fy+sample(1,1)*fx*fy
    return np.minimum((total+2048)>>12,255).astype(np.uint8)

def census(image):
    padded=np.pad(image,2,mode='edge');out=np.zeros(image.shape,np.uint32)
    for y in range(5):
        for x in range(5):
            if x==2 and y==2:continue
            out=(out<<1)|(padded[y:y+H,x:x+W]<image).astype(np.uint32)
    return out

def disparities(left,right):
    a,b=census(left),census(right);xx=np.arange(W)[None,:];yy=np.arange(H)[:,None]
    costs=np.empty((D,H,W),np.uint16)
    for d in range(D):
        shifted=b[:,np.clip(np.arange(W)-d,0,W-1)]
        h=np.bitwise_count(a^shifted).astype(np.uint16)
        vertical=cv2.boxFilter(h,cv2.CV_16U,(1,5),normalize=False,borderType=cv2.BORDER_REPLICATE)
        vertical[(xx<2)|(xx>=W-2)|(xx-d<2)|(xx-d>=W-2)|(yy<4)|(yy>=H-4)]=255
        costs[d]=cv2.boxFilter(vertical,cv2.CV_16U,(5,1),normalize=False,borderType=cv2.BORDER_REPLICATE)
    results=[]
    for direction in [-1,1]:
        values=np.empty((D,H,W),np.uint32)
        for d in range(D):
            source=costs[d] if direction<0 else costs[d][:,np.clip(np.arange(W)+d,0,W-1)]
            valid=(xx+direction*d>=4)&(xx+direction*d<W-4)
            if direction>0:valid=valid&((xx//4)*4+d<W-4)
            values[d]=np.where(valid,source.astype(np.uint32)*D+d,INVALID)
        top=np.sort(np.partition(values,3,axis=0)[:4],axis=0)
        bestd=(top[0]%D).astype(np.int16);best=top[0]//D
        second=np.full((H,W),INVALID,np.uint32)
        for k in range(1,4):
            allowed=(top[k]!=INVALID)&(np.abs((top[k]%D).astype(np.int16)-bestd)>1)
            second=np.minimum(second,np.where(allowed,top[k]//D,INVALID))
        valid=(top[0]!=INVALID)&(bestd>0)&(bestd<D-1)&((second==INVALID)|(second.astype(np.uint64)*90>best.astype(np.uint64)*100))
        valid&=(xx>=4)&(xx<W-4)&(yy>=6)&(yy<H-6)
        results.append(np.where(valid,bestd,-1).astype(np.int16))
    return results

def percentiles(x):return dict(zip(['p50','p95','p99'],map(float,np.percentile(x,[50,95,99]))))
def analyze(p):
    runtime=json.loads((p/'runtime.json').read_text());a=np.genfromtxt(p/'depth.csv',delimiter=',',names=True)
    capture=np.genfromtxt(p/'capture.csv',delimiter=',',names=True)
    a=a[a['api_ready_ns']>=runtime['first_api_ready_ns']+2e9]
    report=dict(runtime=runtime,capture_fps=float((len(capture)-1)*1e9/(capture[-1]['stamp_ns']-capture[0]['stamp_ns'])),depth_fps=float((len(a)-1)*1e9/(a[-1]['depth_ready_ns']-a[0]['depth_ready_ns'])),depth_valid_fraction=percentiles(a['valid_pixels']/(W*H)))
    report['timing_ms']={name:percentiles(value) for name,value in [('gpu',a['gpu_ms']),('rectify_half',a['rectify_ms']),('process',(a['depth_ready_ns']-a['process_begin_ns'])/1e6),('capture_ready_from_driver_estimate',(a['api_ready_ns']-a['stamp_ns'])/1e6),('queue',(a['process_begin_ns']-a['api_ready_ns'])/1e6),('depth_ready_from_driver_estimate',(a['depth_ready_ns']-a['stamp_ns'])/1e6)]}
    windows=[]
    for start in np.arange(a[0]['depth_ready_ns'],a[-1]['depth_ready_ns']-10e9,10e9):
        block=a[(a['depth_ready_ns']>=start)&(a['depth_ready_ns']<start+10e9)]
        windows.append(dict(offset_s=float((start-a[0]['depth_ready_ns'])/1e9),fps=len(block)/10,gaps=int(np.maximum(np.diff(block['index'])-1,0).sum())))
    report['windows_10s']=windows
    for name in ['gray','depth']:
        e=np.genfromtxt(p/f'{name}-encoder.csv',delimiter=',',names=True)
        e=e[e['source_stamp_ns']>=a[0]['stamp_ns']]
        report[name+'_encoder_ms']=dict(depth_to_encoded=percentiles((e['encoded_ready_ns']-e['depth_ready_ns'])/1e6),source_estimate_to_encoded=percentiles((e['encoded_ready_ns']-e['source_stamp_ns'])/1e6))
    idx=int((p/'sample-index.txt').read_text());raw0=np.fromfile(p/'sample-cam0.u16','<u2').reshape(1280,1088);raw1=np.fromfile(p/'sample-cam1.u16','<u2').reshape(1280,1088)
    left=remap(raw1,p/'left-map.i32',(W,H));right=remap(raw0,p/'right-map.i32',(W,H))
    actual_left=np.fromfile(p/f'sample-{idx}-left.u8',np.uint8).reshape(H,W)
    gray=np.fromfile(p/f'sample-{idx}-gray.nv12',np.uint8).reshape(1920,2176)[:1280]
    params=json.loads((p/'parameters.json').read_text())
    eyes=[remap(raw1,p/'full-left-map.i32',(1088,1280)),remap(raw0,p/'full-right-map.i32',(1088,1280))]
    expected_gray=np.concatenate(eyes if params.get('gray_order')=='cam1_left_then_cam0_right' else eyes[::-1],axis=1)
    report['cpu_remap_exact']=dict(full_gray=bool(np.array_equal(gray,expected_gray)),half_left=bool(np.array_equal(left,actual_left)))
    dl,dr=disparities(left,right);xx=np.arange(W)[None,:];yy=np.arange(H)[:,None];xr=xx-dl;xi=np.clip(xr,0,W-1)
    vl=np.fromfile(p/'left-valid.u8',np.uint8).reshape(H,W);vr=np.fromfile(p/'right-valid.u8',np.uint8).reshape(H,W)
    valid=(vl!=0)&(dl>0)&(xr>=0)&(xr<W)&(vr[yy,xi]!=0)&(dr[yy,xi]>0)&(np.abs(dl-dr[yy,xi])<=1)
    fb=np.float32(float((p/'focal-baseline.txt').read_text()))
    expected=np.where(valid,fb/np.maximum(dl,1).astype(np.float32),np.nan)
    actual=np.fromfile(p/f'sample-{idx}-depth.f32','<f4').reshape(H,W)
    same=bool(np.array_equal(np.isfinite(actual),valid));common=valid&np.isfinite(actual)
    report['cpu_depth_replay']=dict(valid_mask_exact=same,valid_pixels=int(valid.sum()),max_depth_error_m=float(np.abs(expected[common]-actual[common]).max()),all_positive=bool(np.all(actual[np.isfinite(actual)]>0)))
    cv2.imwrite(str(p/'rectified-gray.png'),gray)
    color=cv2.cvtColor(np.fromfile(p/f'sample-{idx}-color.nv12',np.uint8).reshape(960,W),cv2.COLOR_YUV2BGR_NV12)
    cv2.imwrite(str(p/'preview.png'),np.concatenate([cv2.cvtColor(left,cv2.COLOR_GRAY2BGR),color],axis=1))
    (p/'analysis.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
    assert all(report['cpu_remap_exact'].values()) and same and report['cpu_depth_replay']['max_depth_error_m']<1e-5

if __name__=='__main__':analyze(ROOT/sys.argv[1])
