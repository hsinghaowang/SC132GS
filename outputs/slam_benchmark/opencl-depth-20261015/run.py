"""Host-side bounded OpenCL experiment orchestration."""
from pathlib import Path
import subprocess
import json
import sys

ROOT = Path(__file__).resolve().parent
HOST = 'ubuntu@192.168.137.226'
SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=6', HOST]


def remote(command, source=None, timeout=30):
    result = subprocess.run(SSH+[command], input=source, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace')+result.stdout.decode(errors='replace'))
    return result.stdout


if __name__ == '__main__':
    name = sys.argv[1] if len(sys.argv) > 1 else 'before'
    result = remote('python3 -', (ROOT/'probe.py').read_bytes())
    (ROOT/f'{name}.json').write_bytes(result)
    if name == 'after':
        before = json.loads((ROOT/'before.json').read_text())
        after = json.loads(result)
        (ROOT/'preservation.json').write_text(json.dumps(dict(
            service_active_and_main_pid_unchanged=before['service']==after['service'],
            saved_settings_sha256_unchanged=before['settings_hash']==after['settings_hash'],
            gpu_platform_enumeration_passed=after['platform_error'] == 0), indent=2)+'\n')
        assert before['settings_hash'] == after['settings_hash']
        assert after['settings_hash']['returncode'] == 0
        assert before['service'] == after['service'], 'Camera service PID/state changed; see preservation.json'
    print(result.decode())
