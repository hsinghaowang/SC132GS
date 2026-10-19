"""RAW10 preview and descriptive temporal statistics; standard library only."""
import argparse
import binascii
import json
import math
from pathlib import Path
import re
import statistics
import struct
import zlib

def png(path, width, height, pixels):
    def chunk(tag, data):
        body = tag+data
        return struct.pack('>I', len(data))+body+struct.pack('>I', binascii.crc32(body)&0xffffffff)
    rows = b''.join(b'\0'+pixels[y*width:(y+1)*width] for y in range(height))
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('>IIBBBBB',width,height,8,0,0,0,0))+
                     chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b''))

def pixel(raw, stride, x, y):
    group, lane = divmod(x,4)
    offset = y*stride+group*5
    return (raw[offset+lane]<<2)|((raw[offset+4]>>(lane*2))&3)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    root = args.directory
    stride, width, height = map(int,re.search(r'stride=(\d+) width=(\d+) height=(\d+)',
        (root/'capture.log').read_text()).groups())
    files = sorted(root.glob('frame-*.raw'),key=lambda p:int(p.stem.split('-')[1]))
    if len(files) < 2: raise RuntimeError('Need multiple actual RAW frames')
    # Same central field of view on a uniform grid. Lighting, motion and
    # black-level calibration remain limitations of this scene measurement.
    coordinates = [(int(width*(0.1+0.8*x/63)),int(height*(0.1+0.8*y/63)))
                   for y in range(64) for x in range(64)]
    samples = []
    first = None
    for path in files:
        raw = path.read_bytes()
        if len(raw) < stride*height: raise RuntimeError('Short RAW frame')
        if first is None: first = raw
        samples.append([pixel(raw,stride,x,y) for x,y in coordinates])
    frame_means = [statistics.fmean(s) for s in samples]
    per_pixel_means = [statistics.fmean(s[i] for s in samples) for i in range(len(coordinates))]
    usable = [i for i,value in enumerate(per_pixel_means) if 8<value<1000]
    variances = [statistics.variance(s[i] for s in samples) for i in usable]
    residual_variances = [statistics.variance(samples[f][i]-frame_means[f] for f in range(len(samples))) for i in usable]
    result = dict(width=width,height=height,stride=stride,frames=len(samples),
                  central_roi_mean_dn=statistics.fmean(frame_means),
                  central_roi_median_dn=statistics.median(per_pixel_means),
                  frame_mean_std_dn=statistics.stdev(frame_means),
                  usable_grid_points=len(usable),
                  temporal_rms_dn=math.sqrt(statistics.fmean(variances)) if usable else None,
                  common_offset_removed_temporal_rms_dn=math.sqrt(statistics.fmean(residual_variances)) if usable else None,
                  clipped_fraction=sum(v>=1020 for s in samples for v in s)/(len(samples)*len(coordinates)))
    scale=2 if width==1088 else 1
    preview=bytes(min(255,pixel(first,stride,x*scale,y*scale)>>2)
                  for y in range(height//scale) for x in range(width//scale))
    png(root/'raw-preview.png',width//scale,height//scale,preview)
    # A fixed 4x display multiplier reveals dark detail; not a sensitivity measurement.
    png(root/'raw-preview-display4x.png',width//scale,height//scale,bytes(min(255,v*4) for v in preview))
    (root/'raw-statistics.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))

if __name__=='__main__': main()
