#!/usr/bin/env python3
"""Lossless RAW10 inputs; separate 8-bit grayscale content preview only."""
import argparse,hashlib,json
from pathlib import Path
import numpy as np
from PIL import Image
p=argparse.ArgumentParser();p.add_argument('raw',type=Path);a=p.parse_args()
views=[];evidence=[]
for eye in (0,1):
    path=a.raw/f'pair-eye{eye}.raw10';data=path.read_bytes()
    assert len(data)==1360*1280
    groups=np.frombuffer(data,dtype=np.uint8).reshape(1280,272,5)
    values=(groups[:,:,:4].astype(np.uint16)<<2)|((groups[:,:,4,None]>>np.array([0,2,4,6]))&3)
    values=values.reshape(1280,1088)
    assert int(values.max()-values.min())>32
    views.append((values>>2).astype(np.uint8))
    evidence.append({'eye':eye,'sha256':hashlib.sha256(data).hexdigest(),
                     'min':int(values.min()),'max':int(values.max()),'mean':float(values.mean())})
Image.fromarray(np.hstack(views)).save(a.raw/'pair-preview.png')
(a.raw/'image-evidence.json').write_text(json.dumps({'timestamp_ns':int((a.raw/'pair-timestamp.txt').read_text()),'eyes':evidence,
    'preview':'8-bit grayscale RAW10 content preview; no exposure alignment measurement'},indent=2)+'\n')
