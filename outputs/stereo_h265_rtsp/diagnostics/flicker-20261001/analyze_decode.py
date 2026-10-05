import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\000403\AppData\Local\Temp\sc132gs-flicker-tools")
import numpy as np
from PIL import Image

root = Path(__file__).parent
ffmpeg = r"C:\Users\000403\AppData\Local\Temp\sc132gs-flicker-tools\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"
width, height = 2176, 1280
size = width * height
log = (root / "decode.log").open("wb")
decoder = subprocess.Popen([ffmpeg, "-hide_banner", "-loglevel", "warning", "-i", str(root / "rtsp-annexb.h265"), "-f", "rawvideo", "-pix_fmt", "gray", "-"], stdout=subprocess.PIPE, stderr=log)
count = 0
maxima = [0.0, 0.0]
best = [None, None]
events = []
while True:
    data = decoder.stdout.read(size)
    if not data:
        break
    if len(data) != size:
        raise RuntimeError(f"short decoded frame {len(data)}")
    frame = np.frombuffer(data, dtype=np.uint8).reshape(height, width)
    for eye in range(2):
        plane = frame[:, eye * 1088:(eye + 1) * 1088].astype(np.float32)
        # A vertical test pattern should be constant along each column.
        deviation = plane[1:-1] - (plane[:-2] + plane[2:]) * 0.5
        row_strength = np.mean(np.abs(deviation), axis=1)
        row = int(np.argmax(row_strength)) + 1
        score = float(row_strength[row - 1])
        if score > maxima[eye]:
            maxima[eye] = score
            best[eye] = {"frame": count, "row": row, "row_mean_absolute_deviation": score}
            # Match the temporary VLC display gamma to make a faint line visible.
            displayed = np.clip((frame.astype(np.float32) / 255.0) ** (1.0 / 2.5) * 255.0, 0, 255).astype(np.uint8)
            Image.fromarray(displayed).save(root / f"decoded-eye{eye}-strongest.png")
        if score >= 0.25:
            events.append({"frame": count, "eye": eye, "row": row, "score": score})
    count += 1
decoder.stdout.close()
result = decoder.wait()
log.close()
report = {"frames": count, "decoder_exit": result, "strongest": best, "event_count": len(events), "events": events[:60]}
(root / "decode-analysis.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
