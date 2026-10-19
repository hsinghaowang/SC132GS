import csv
import json
from pathlib import Path
import numpy as np

base=Path(__file__).resolve().parent
root=base/'live-calibration-20261013/smoke-10s'
with (root/'camera-frames.csv').open() as file:frames=list(csv.DictReader(file))
eyes=[[row for row in frames if int(row['eye'])==eye] for eye in (0,1)]
times=[np.array([int(row['receiver_timestamp_ns']) for row in eye],dtype=np.int64) for eye in eyes]
nearest=[]
for timestamp in times[0]:nearest.append(float(np.min(np.abs(times[1]-timestamp)))/1e6)
result=dict(camera_saved=[len(eye) for eye in eyes],
    nearest_selected_driver_stamp_delta_ms=dict(p50=float(np.percentile(nearest,50)),p95=float(np.percentile(nearest,95)),max=float(max(nearest))),
    camera_selected_rate_hz=[float((len(eye)-1)*1e9/(eye[-1]-eye[0])) for eye in times],
    timestamp_flags=sorted(set(int(row['flags']) for row in frames)),
    imu=json.loads((root/'imu-summary.json').read_text()),
    camera_state_preserved=json.loads((root/'transaction.json').read_text())['saved_state_preserved'],
    exposure_and_IMU_sample_synchronization_validated=False)
(root/'audit.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
