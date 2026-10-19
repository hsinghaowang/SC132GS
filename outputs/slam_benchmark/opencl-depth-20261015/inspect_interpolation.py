"""Compare OpenCV backends before selecting GPU interpolation semantics."""
import importlib.util
from pathlib import Path
import sys
import cv2
import numpy as np

root=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('live_depth',root.parent/'live-depth/server.py')
module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
processor=module.StereoDepth(root.parent/'calibration-ready-20261014/geometry-analysis/stereo-candidate.npz')
frame=cv2.imread(str(root.parent/'calibration-ready-20261014/rtsp-decode-stable/decoded.png'),0)
source=cv2.flip(frame[:,1088:],1);mx,my=processor.maps[0]
integer,fraction=cv2.convertMaps(mx,my,cv2.CV_16SC2)
floating=cv2.remap(source,mx,my,cv2.INTER_LINEAR)
fixed=cv2.remap(source,integer,fraction,cv2.INTER_LINEAR)
x,y=integer[:,:,0].astype(int),integer[:,:,1].astype(int)
fx,fy=(fraction&31).astype(int),(fraction>>5).astype(int)
def sample(x,y):
    inside=(x>=0)&(x<1088)&(y>=0)&(y<1280)
    return np.where(inside,source[np.clip(y,0,1279),np.clip(x,0,1087)],0).astype(int)
exact=((sample(x,y)*(32-fx)*(32-fy)+sample(x+1,y)*fx*(32-fy)+
        sample(x,y+1)*(32-fx)*fy+sample(x+1,y+1)*fx*fy+512)>>10).astype(np.uint8)
for label,image in [('floating',floating),('fixed',fixed)]:
    delta=np.abs(image.astype(int)-exact.astype(int))
    print(label,dict(different=int((delta>0).sum()),max=int(delta.max())))
if hasattr(cv2,'ipp'):
    print('IPP',cv2.ipp.useIPP(),cv2.ipp.getIppVersion())
    cv2.ipp.setUseIPP(False)
    generic=cv2.remap(source,mx,my,cv2.INTER_LINEAR)
    delta=np.abs(generic.astype(int)-exact.astype(int))
    print('without_IPP',dict(different=int((delta>0).sum()),max=int(delta.max())))
