import json
import pathlib
import sys
sys.path.insert(0, r"C:\Users\000403\AppData\Local\Temp\sc132gs-flicker-tools")
import numpy as np
from PIL import Image

root = pathlib.Path(__file__).parent
report = {}
for name in ("cam0", "cam1", "linear-historical"):
    data = np.frombuffer((root / f"{name}.raw").read_bytes()[:1740800], np.uint8).reshape(-1, 5)
    pixels = ((data[:, :4].astype(np.uint16) << 2) |
              ((data[:, 4, None] >> np.arange(4, dtype=np.uint8)[None, :] * 2) & 3)).reshape(1280, 1088)
    p = pixels.astype(np.float32)
    Image.fromarray((pixels >> 2).astype(np.uint8)).save(root / f"{name}-direct.png")
    result = {}
    for label, start, end in (("top", 0, 640), ("bottom", 640, 1280)):
        crop = p[start:end]
        phases = np.stack([crop[0::2,0::2],crop[0::2,1::2],crop[1::2,0::2],crop[1::2,1::2]], axis=-1)
        mean = phases.mean(axis=-1)
        valid = (mean > 100) & (mean < 850)
        ratios = phases[valid] / mean[valid,None]
        result[label] = dict(phase_relative_median=np.median(ratios, axis=0).tolist(),
                             phase_relative_mean=np.mean(ratios, axis=0).tolist(),
                             within_cell_spread_median=float(np.median(np.ptp(phases[valid],axis=-1))))
    report[name] = result
(root / "raw-phase-analysis.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
