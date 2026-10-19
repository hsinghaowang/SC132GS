"""Observe the container's actual IPC namespace during the full experiment."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

base=Path('/home/ubuntu/ros2_humble_ws/slam_benchmark')
evidence=base/'ros-results/delivery-repair-20261013'
pid=int(subprocess.check_output(['docker','inspect','--format','{{.State.Pid}}','ros2-humble'],text=True))
shm=Path('/proc')/str(pid)/'root/dev/shm'
assert shm.is_dir()
metadata=dict(pid=__import__('os').getpid(),container_init_pid=pid,actual_container_shm=str(shm),
              source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),sampling_interval_s=1,
              reason='Initial short sampler watched host /dev/shm; full sampler watches container namespace')
(evidence/'full-shm-monitor.json').write_text(json.dumps(metadata,indent=2))
closed=threading.Event()
def sample():
    with (evidence/'full-container-shm.jsonl').open('x') as file:
        while not closed.is_set():
            entries=[]
            for path in shm.glob('fastrtps*'):
                try:
                    stat=path.stat();entries.append(dict(name=path.name,size=stat.st_size,mtime_ns=stat.st_mtime_ns))
                except OSError:pass
            file.write(json.dumps(dict(monotonic_ns=time.monotonic_ns(),segments=entries))+'\n');file.flush()
            closed.wait(1)
worker=threading.Thread(target=sample);worker.start()
try:
    result=subprocess.run([sys.executable,str(base/'run-delivery-repair.py'),'full'])
finally:
    closed.set();worker.join()
raise SystemExit(result.returncode)
