"""Build independent OpenCV remap fixtures from the preserved stereo map."""
from pathlib import Path
import argparse
import tarfile
import numpy as np
import cv2

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('backup', type=Path)
p.add_argument('output', type=Path)
a=p.parse_args()
a.output.mkdir(exist_ok=False)
with tarfile.open(a.backup) as t:
    data=t.extractfile('backup/files/home/ubuntu/main10-rectification-20261016/fixtures/calibration.map').read()
header=data[:76]
w,h=1088,1280
y,x=np.indices((h,w))
inputs={}
for eye in (0,1):
    codes=(x*(3+eye*4)+y*(5+eye*6)+eye*79)
    inputs[eye,8]=(codes%220+16).astype(np.uint8)
    inputs[eye,10]=(codes%1024).astype(np.uint16)
    inputs[eye,0]=(codes%256).astype(np.uint8)
    inputs[eye,0].tofile(a.output/f'cam{eye}-full.u8')
    inputs[eye,8].tofile(a.output/f'cam{eye}.u8')
    inputs[eye,10].tofile(a.output/f'cam{eye}.u16')
identity=np.stack((x*32,y*32),axis=-1).astype('<i4')
for name,raw in [('identity',header+np.stack((identity,identity)).tobytes()),('calibration',data)]:
    (a.output/f'{name}.map').write_bytes(raw)
    maps=np.frombuffer(raw, dtype='<i4',offset=76).reshape(2,h,w,2).astype(np.float32)/32
    for bits in (8,10):
        views=[cv2.remap(inputs[eye,bits],maps[index,:,:,0],maps[index,:,:,1],cv2.INTER_LINEAR,
                   borderMode=cv2.BORDER_CONSTANT,borderValue=16 if bits==8 else 0)
                   for index,eye in enumerate((1,0))]
        np.hstack(views).tofile(a.output/f'{name}-expected.u{8 if bits==8 else 16}')
    views=[cv2.remap(inputs[eye,0],maps[index,:,:,0],maps[index,:,:,1],cv2.INTER_LINEAR,
               borderMode=cv2.BORDER_CONSTANT,borderValue=0) for index,eye in enumerate((1,0))]
    np.hstack(views).tofile(a.output/f'{name}-expected-full.u8')
(a.output/'invalid.map').write_bytes(b'bad map')
print('Independent OpenCV fixtures created', a.output)
