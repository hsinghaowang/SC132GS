#!/usr/bin/env bash
set -e
source /opt/ros/humble/setup.bash
source /ws/slam_benchmark/openvins_ws/install/setup.bash
set -uo pipefail
base=/ws/slam_benchmark
root=$base/feature-sweep
mkdir -p "$root/configs" "$root/results"
python3 - "$base" "$root" <<'PY'
import hashlib,json,re,shutil,sys
from pathlib import Path
base,root=map(Path,sys.argv[1:])
source=base/'openvins_ws/src/open_vins/config/euroc_mav'
original=(source/'estimator_config.yaml').read_text()
manifest={"parameter":"num_pts", "implementation_semantics":"total tracking target divided by num_cameras=2", "runs_per_setting_initial_screen":1, "paced_hz":20, "settings":[]}
for count in (200,150,100):
    destination=root/'configs'/str(count)
    if destination.exists(): raise RuntimeError(f'Existing experiment config: {destination}')
    shutil.copytree(source,destination)
    revised,n=re.subn(r'(?m)^num_pts: 200[^\n]*',f'num_pts: {count} # total target; {count//2} per camera in pinned implementation',original)
    assert n==1
    (destination/'estimator_config.yaml').write_text(revised)
    manifest['settings'].append({'num_pts':count,'target_per_camera':count//2,'config_sha256':hashlib.sha256(revised.encode()).hexdigest()})
(root/'experiment.json').write_text(json.dumps(manifest,indent=2))
PY
# Interleave settings; reverse dataset order for the middle setting.
for count in 200 150 100; do
  datasets="MH_01_easy V2_02_medium"
  [ "$count" = 150 ] && datasets="V2_02_medium MH_01_easy"
  for dataset in $datasets; do
    out=$root/results/$dataset-pts$count-paced-1
    [ ! -e "$out" ] || { echo "Existing output: $out"; exit 1; }
    echo "START $dataset num_pts=$count $(date -u +%FT%TZ)"
    python3 "$base/measure-run.py" "$out" "$base/euroc-runner/build/euroc_benchmark" "$root/configs/$count/estimator_config.yaml" "$base/datasets/$dataset/mav0" "$out" 1 0
    echo "DONE $dataset num_pts=$count $(date -u +%FT%TZ)"
  done
done
echo SCREEN_COMPLETE
