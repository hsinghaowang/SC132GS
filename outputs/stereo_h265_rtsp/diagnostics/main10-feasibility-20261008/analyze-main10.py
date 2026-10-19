import json
import sys
from pathlib import Path
import numpy as np

path, width, height = Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
data = np.fromfile(path, dtype='<u2')
frame_samples = width * height * 3 // 2
if data.size % frame_samples:
    raise ValueError('Decoded buffer does not match tightly packed I420_10LE')
frames = data.reshape(-1, frame_samples)
reports = []
for i, frame in enumerate(frames):
    luma = frame[:width*height].reshape(height, width).astype(np.int32)
    expected = 64 + (np.arange(width, dtype=np.int32)*876//(width-1)+i)%877
    error = luma - expected[None, :]
    chroma = frame[width*height:]
    reports.append({
        'frame': i, 'min': int(luma.min()), 'max': int(luma.max()),
        'unique_luma_levels': int(np.unique(luma).size),
        'low_two_bit_histogram': np.bincount((luma & 3).ravel(), minlength=4).tolist(),
        'mae': float(np.abs(error).mean()), 'rmse': float(np.sqrt(np.mean(error.astype(float)**2))),
        'p99_abs_error': float(np.percentile(np.abs(error),99)),
        'max_abs_error': int(np.abs(error).max()),
        'chroma_min': int(chroma.min()), 'chroma_max': int(chroma.max()),
    })
print(json.dumps({'width':width,'height':height,'decoded_frames':len(frames),
    'input':'synthetic linear P010 gradient; no camera frames',
    'frames':reports}, indent=2))
