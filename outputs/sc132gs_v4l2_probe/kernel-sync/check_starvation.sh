#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/ubuntu/sc132gs-kernel-sync-20261014
CONTROL=/sys/bus/platform/devices/acb3000.camss/fsync_control
cd "$ROOT"
bash run_raw_probe.sh armed-starvation 30 &
run=$!
for ((n=0;n<100;n++)); do
    probe=$(pgrep -f '^/home/ubuntu/sc132gs-kernel-sync-20261014/raw-sync-probe ' || true)
    if [[ -n $probe ]]; then break; fi
    sleep 0.1
done
[[ -n $probe ]]
sleep 3
kill -STOP "$probe"
trap 'kill -CONT "$probe" 2>/dev/null || true' EXIT
cat "$CONTROL" > armed-starvation-before.txt
sleep 1
cat "$CONTROL" > armed-starvation-paused.txt
kill -CONT "$probe"
set +e
wait "$run"
rc=$?
set -e
[[ $rc != 0 ]]
python3 - <<'PY'
from pathlib import Path
import json
read=lambda p:dict(t.split('=',1) for t in Path(p).read_text().split())
a=read('armed-starvation-before.txt');b=read('armed-starvation-paused.txt')
assert a['error']=='0' and b['error']=='9'
assert int(b['pulses'])>int(a['pulses']) and b['running']=='1'
assert Path('armed-starvation-exit.txt').read_text().strip()!='0'
Path('armed-starvation-result.json').write_text(json.dumps({'passed':True,'error':9,'producer_continues':True,'before':a,'paused':b},indent=2)+'\n')
PY
