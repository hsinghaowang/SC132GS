"""Summarize completed GPU-remap evidence and make a diagnostic comparison."""
import json
from pathlib import Path
import cv2
import numpy as np

root=Path(__file__).resolve().parent
out=root/'rectify-photo'
photo=json.loads((out/'benchmark.json').read_text())
border=json.loads((root/'rectify-border-check/benchmark.json').read_text())
assert photo['gpu_metrics']['cpu_gpu_rectification_equal']=='1'
assert border['gpu_metrics']['cpu_gpu_rectification_equal']=='1'
assert photo['whole_image_disparity_equal_to_previous']
for report in (photo,border):
    assert report['camera_state_same_during_this_run'] and report['camera_active_before_and_after']
frame=cv2.imread(str(root.parent/'calibration-ready-20261014/rtsp-decode-stable/decoded.png'),0)
original=cv2.resize(cv2.flip(frame[:,1088:],1),(544,640),interpolation=cv2.INTER_AREA)
corrected=cv2.imread(str(out/'rectified-left.png'),0)
canvas=np.full((720,1120,3),22,np.uint8)
canvas[48:688,8:552]=cv2.cvtColor(original,cv2.COLOR_GRAY2BGR)
canvas[48:688,568:1112]=cv2.cvtColor(corrected,cv2.COLOR_GRAY2BGR)
for label,xy in [('ORIGINAL LEFT (scaled for display)',(8,30)),('GPU RECTIFIED LEFT 544 x 640',(568,30)),
                 ('One GPU sampling pass: mirror restoration + fisheye/stereo rectification + resize',(8,710))]:
    cv2.putText(canvas,label,xy,0,.53,(235,235,235),1,cv2.LINE_AA)
assert cv2.imwrite(str(out/'rectification-comparison.png'),canvas)
summary=dict(gpu_stereo_remap_median_ms=float(photo['gpu_metrics']['stage_0_median_ms']),
    source_stereo_size=[2176,1280],rectified_eye_size=[544,640],
    photo_rectification_matches_fixed_OpenCV_reference=True,border_fractional_and_mirror_fixture_passed=True,
    disparity_matches_separate_CPU_fixed_remap_reference=True,
    processing_including_upload_remap_matching_readback_median_ms=float(photo['gpu_metrics']['wall_median_ms']),
    processing_including_upload_remap_matching_readback_p95_ms=float(photo['gpu_metrics']['wall_p95_ms']),
    samples=int(photo['gpu_metrics']['measured_iterations']),binning_changed=False,
    camera_configuration_changed=False,metric_accuracy_verified=False,live_stream_updated=False,
    warning='Fixed-coordinate interpolation differs by up to 2 gray levels from the previous OpenCV floating-map path on this photo.')
(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))
