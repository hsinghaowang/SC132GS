import csv
import json
import sys
from pathlib import Path

root=Path(sys.argv[1])
rows=[]
for cam in ('cam0','cam1'):
    with (root/cam/'data.csv').open() as stream:
        data=[r for r in csv.reader(stream) if r and not r[0].startswith('#')]
    assert all((root/cam/'data'/r[1]).is_file() for r in data)
    rows.append(data)
left,right=rows
assert [r[0] for r in left]==[r[0] for r in right], 'stereo timestamp mismatch in original integer strings'
times=[int(r[0]) for r in left]
assert all(b>a for a,b in zip(times,times[1:]))
with (root/'imu0/data.csv').open() as stream:
    imu=[int(r[0]) for r in csv.reader(stream) if r and not r[0].startswith('#')]
assert all(b>a for a,b in zip(imu,imu[1:]))
report={'stereo_pairs':len(times),'imu_samples':len(imu),'all_images_present':True,'exact_integer_stereo_timestamp_match':True,'strictly_monotonic':True,'camera_duration_s':(times[-1]-times[0])/1e9,'camera_interval_ns_min':min(b-a for a,b in zip(times,times[1:])),'camera_interval_ns_max':max(b-a for a,b in zip(times,times[1:]))}
(root/'verified.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report))
