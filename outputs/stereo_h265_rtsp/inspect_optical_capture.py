#!/usr/bin/env python3
"""Audit saved packed RAW10 against recorded tile statistics and render previews."""
import argparse
import json
from pathlib import Path
import struct
import zlib
import numpy as np
from analyze_optical_exposure import read_frames

def png(path,pixels):
    def chunk(kind,data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    height,width=pixels.shape
    rows=b''.join(b'\0'+row.tobytes() for row in pixels)
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,0,0,0,0))+
        chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b''))

def inspect(root):
    frames,width,height,step=read_frames(root/'frames.bin')
    audits=[]
    for metadata in sorted(root.glob('eye*-*.json')):
        if not metadata.with_suffix('.raw10').exists(): continue
        info=json.loads(metadata.read_text())
        eye=int(metadata.stem[3])
        packed=np.fromfile(metadata.with_suffix('.raw10'),dtype=np.uint8)
        groups=packed[:info['height']*info['stride']].reshape(info['height'],info['stride'])[:,:info['width']*5//4].reshape(info['height'],-1,5)
        raw=(groups[:,:,:4].astype(np.uint16)<<2)|((groups[:,:,4,None]>>np.array([0,2,4,6]))&3)
        raw=raw.reshape(info['height'],info['width'])
        tiles=(raw.reshape(height,step,width,step).sum(axis=(1,3))+32)//64
        saturated=(raw>=1018).reshape(height,step,width,step).sum(axis=(1,3))
        match=frames[(frames['eye']==eye)&(frames['sequence']==info['sequence'])]
        if len(match)!=1: raise ValueError('saved RAW frame not uniquely recorded')
        assert np.array_equal(tiles.ravel(),match[0]['tiles']),metadata
        assert np.array_equal(saturated.ravel(),match[0]['saturated']),metadata
        png(metadata.with_suffix('.png'),(raw/4).astype(np.uint8))
        audits.append(dict(file=metadata.name,raw10_tile_means_match=True,saturation_counts_match=True))
    (root/'raw-audit.json').write_text(json.dumps(audits,indent=2))
    print(json.dumps(dict(audited_raw_frames=len(audits),all_match=True)))

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('directory',type=Path)
    inspect(parser.parse_args().directory)
