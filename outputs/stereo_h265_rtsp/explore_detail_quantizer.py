"""Independent NumPy oracle; image codes and census retention are not accuracy."""
from pathlib import Path
import numpy as np,cv2,json
BASE=Path(__file__).resolve().parent
OLD=BASE/'tone-board-evidence-20261016-ae-v3-after-error9-1630/board/replay'
OUT=BASE/'contrast8-evidence-20261016/quantizer-exploration';OUT.mkdir(exist_ok=True)
eyes=[np.fromfile(OLD/f'cam{i}-calibrated-mono10.u16',dtype='<u2').reshape(1280,1088) for i in range(2)]
h=sum(np.bincount(a.ravel(),minlength=1024) for a in eyes)
def lut(cap_multiple):
 q=np.minimum(h,h.sum()*cap_multiple/1024).astype(float);cap=h.sum()*cap_multiple/1024
 for _ in range(1024):
  missing=h.sum()-q.sum();free=q<cap-1e-9
  if missing<1e-7 or not free.any():break
  q[free]+=np.minimum(missing/free.sum(),cap-q[free])
 c=q.cumsum()-q*.5;c=(c-c[0])/(c[-1]-c[0]);return np.floor(255*c+.5).astype(np.uint8)
def stats(raw,y):
 counts=np.bincount(y.ravel(),minlength=256);f=counts[counts>0]/y.size
 sums=np.bincount(y.ravel(),weights=raw.ravel(),minlength=256);mean=np.divide(sums,counts,out=np.zeros(256),where=counts>0)
 mse=float(np.mean((raw.astype(float)-mean[y])**2))
 lost,total=0,0
 for dy in range(-2,3):
  for dx in range(-2,3):
   if not (dy or dx):continue
   a=raw[2:-2,2:-2];b=raw[2+dy:raw.shape[0]-2+dy,2+dx:raw.shape[1]-2+dx]
   p=y[2:-2,2:-2];q=y[2+dy:y.shape[0]-2+dy,2+dx:y.shape[1]-2+dx]
   lost+=int(np.count_nonzero((b<a)!=(q<p)));total+=a.size
 return dict(distinct=int((counts>0).sum()),entropy_bits=float(-(f*np.log2(f)).sum()),conditional_reconstruction_rmse_raw10=mse**.5,census_bit_change_fraction=lost/total,p=np.percentile(y,[1,5,50,95,99]).tolist())
results={}
for cap in (2,4,8):
 table=lut(cap);folder=OUT/f'clip{cap}';folder.mkdir(exist_ok=True)
 rows=[]
 for i,a in enumerate(eyes):
  old=np.fromfile(OLD/f'cam{i}-shared-y8.u8',dtype=np.uint8).reshape(a.shape);new=table[a]
  new.tofile(folder/f'cam{i}-detail-y8.u8');cv2.imwrite(str(folder/f'cam{i}-after.png'),new)
  before=np.clip((old.astype(float)-16)*255/219,0,255).round().astype(np.uint8)
  cv2.imwrite(str(folder/f'cam{i}-comparison.png'),np.concatenate((before,new),axis=1))
  rows.append(dict(cam=i,before=stats(a,old),after=stats(a,new)))
 results[str(cap)]=dict(lut=table.tolist(),eyes=rows)
(OUT/'comparison.json').write_text(json.dumps(results,indent=2));print(json.dumps({k:v['eyes'] for k,v in results.items()}))
