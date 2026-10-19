"""Independent quantizer/remap oracle and same-pixel feature evidence."""
from pathlib import Path
import json,hashlib
import numpy as np,cv2
R=Path(__file__).resolve().parent/'contrast8-evidence-20261016'
B=R/'offline-static';C=R/'backup/files/home/ubuntu/main10-rectification-20261016/depth-calibration'
def quantizer(eyes):
 h=sum(np.bincount(a.ravel(),minlength=1024) for a in eyes);cap=h.sum()*4/1024;q=np.minimum(h,cap).astype(float)
 for _ in range(1024):
  missing=h.sum()-q.sum();free=q<cap-1e-9
  if missing<1e-7 or not free.any():break
  q[free]+=np.minimum(missing/free.sum(),cap-q[free])
 c=q.cumsum()-q*.5;c=(c-c[0])/(c[-1]-c[0]);return np.floor(c*255+.5).astype(np.uint8)
def remap(src,m):
 x,y=m[...,0]>>5,m[...,1]>>5;fx,fy=m[...,0]&31,m[...,1]&31
 def sample(dx,dy):
  xx,yy=x+dx,y+dy;valid=(xx>=0)&(xx<1088)&(yy>=0)&(yy<1280)
  return src[np.clip(yy,0,1279),np.clip(xx,0,1087)].astype(np.uint32)*valid
 return ((sample(0,0)*(32-fx)*(32-fy)+sample(1,0)*fx*(32-fy)+sample(0,1)*(32-fx)*fy+sample(1,1)*fx*fy+512)>>10)
def census_change(ref,y,valid):
 changed=equal_lost=total=0
 mask=cv2.erode((valid>0).astype('u1'),np.ones((5,5),'u1'))[2:-2,2:-2]>0
 for dy in range(-2,3):
  for dx in range(-2,3):
   if not(dx or dy):continue
   a=ref[2:-2,2:-2];b=ref[2+dy:ref.shape[0]-2+dy,2+dx:ref.shape[1]-2+dx]
   p=y[2:-2,2:-2];q=y[2+dy:y.shape[0]-2+dy,2+dx:y.shape[1]-2+dx]
   changed+=int(np.count_nonzero(((b<a)!=(q<p))&mask));equal_lost+=int(np.count_nonzero((b!=a)&(q==p)&mask));total+=int(mask.sum())
 return dict(census_bit_change_fraction=changed/total,non_equal_raw_pairs_merged_fraction=equal_lost/total,valid_comparisons=total)
def image_stats(y):
 h=np.bincount(y.ravel(),minlength=256);p=h[h>0]/y.size
 return dict(distinct=int((h>0).sum()),entropy_bits=float(-(p*np.log2(p)).sum()),percentiles=np.percentile(y,[1,5,50,95,99]).tolist())
def label(image,text):
 canvas=cv2.copyMakeBorder(image,44,0,0,0,cv2.BORDER_CONSTANT,value=24)
 cv2.putText(canvas,text,(12,29),cv2.FONT_HERSHEY_SIMPLEX,.8,255,1,cv2.LINE_AA);return canvas
results={}
for folder in ('replay-current10','replay-final-history'):
 d=B/folder;raw=[np.fromfile(d/f'cam{i}-calibrated-mono10.u16',dtype='<u2').reshape(1280,1088) for i in (0,1)]
 old=[np.fromfile(d/f'cam{i}-shared-y8.u8',dtype='u1').reshape(1280,1088) for i in (0,1)]
 new=[np.fromfile(d/f'cam{i}-detail-y8.u8',dtype='u1').reshape(1280,1088) for i in (0,1)]
 table=quantizer(raw);oracle=[int(np.max(np.abs(table[a].astype(int)-b.astype(int)))) for a,b in zip(raw,new)]
 assert oracle==[0,0],oracle
 rows=[]
 for eye,map_name in ((1,'left-map.i32'),(0,'right-map.i32')):
  m=np.fromfile(C/map_name,dtype='<i4').reshape(640,544,2);ref=remap(raw[eye],m);a=remap(old[eye],m);b=remap(new[eye],m)
  if eye==1:
   assert np.array_equal(cv2.imread(str(d/'candidate-matching-left.pgm'),0),b.astype('u1'))
   assert np.array_equal(cv2.imread(str(d/'shared-matching-left.pgm'),0),a.astype('u1'))
   assert np.array_equal(cv2.imread(str(d/'reference10-matching-left.pgm'),0),np.minimum(255,(ref+2)>>2).astype('u1'))
  valid=np.fromfile(C/('left-valid.u8' if eye==1 else 'right-valid.u8'),dtype='u1').reshape(640,544)
  rows.append(dict(cam=eye,native_old=image_stats(old[eye]),native_new=image_stats(new[eye]),rectified_old=census_change(ref,a,valid),rectified_new=census_change(ref,b,valid)))
 # Same saved mono10/RAW, same eye, same orientation: no time-varying scene.
 a=np.clip((old[1].astype(float)-16)*255/219,0,255).round().astype('u1');b=new[1]
 compare=np.hstack((label(a,'Before: shared BT.709 Y16-235'),label(b,'After: detail-oriented Y0-255')))
 cv2.imwrite(str(R/(folder+'-comparison.png')),compare)
 j=json.loads((d/'comparison.json').read_text());z=[np.fromfile(d/name,dtype='<f4') for name in ('shared-depth.f32','candidate-depth.f32','reference10-depth.f32')]
 mask=np.logical_and.reduce([np.isfinite(v)&(v>0) for v in z]);fb=j['focal_times_baseline_m_px']
 da=np.abs(fb/z[0][mask]-fb/z[2][mask]);db=np.abs(fb/z[1][mask]-fb/z[2][mask])
 colors=[]
 for name in ('shared','candidate'):
  nv=np.fromfile(d/(name+'-depth-color.nv12'),dtype='u1').reshape(960,544);colors.append(cv2.cvtColor(nv,cv2.COLOR_YUV2BGR_NV12))
 cv2.imwrite(str(R/(folder+'-depth-comparison.png')),np.hstack(colors))
 results[folder]=dict(oracle_max_difference=oracle,eyes=rows,common_valid_pixels=int(mask.sum()),old_disparity_difference_px=float(da.mean()),new_disparity_difference_px=float(db.mean()),old_halfpx_fraction=float((da>.5).mean()),new_halfpx_fraction=float((db>.5).mean()),old_valid_fraction=j['shared_depth']['valid_fraction'],new_valid_fraction=j['candidate_depth']['valid_fraction'],new_gained_unverified=j['old_vs_candidate']['gained_valid_pixels'],new_lost=j['old_vs_candidate']['lost_valid_pixels'])
(R/'same-raw-analysis.json').write_text(json.dumps(results,indent=2));print(json.dumps(results))
