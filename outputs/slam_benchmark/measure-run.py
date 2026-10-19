"""Run one benchmark, retaining resource use and one-second thermal samples."""
import csv
import json
import os
import resource
import subprocess
import sys
import time
from pathlib import Path

output = Path(sys.argv[1])
output.mkdir(parents=True, exist_ok=True)
with (output/'run.log').open('w') as log, (output/'platform-samples.csv').open('w') as sample_file:
    start = time.monotonic()
    process = subprocess.Popen(sys.argv[2:], stdout=log, stderr=subprocess.STDOUT)
    writer = csv.writer(sample_file)
    writer.writerow(['elapsed_s', 'thermal_type', 'temperature_raw', 'cpu_frequencies_khz'])
    while process.poll() is None:
        frequencies = {str(p.parent.parent.name):p.read_text().strip() for p in Path('/sys/devices/system/cpu').glob('cpu[0-9]*/cpufreq/scaling_cur_freq')}
        for zone in Path('/sys/class/thermal').glob('thermal_zone*'):
            try:
                writer.writerow([time.monotonic()-start, (zone/'type').read_text().strip(), (zone/'temp').read_text().strip(), json.dumps(frequencies)])
            except OSError:
                pass
        sample_file.flush()
        time.sleep(1)
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    elapsed = time.monotonic()-start
    metadata = {'exit_code':process.returncode, 'elapsed_wrapper_s':elapsed, 'cpu_user_s':usage.ru_utime, 'cpu_system_s':usage.ru_stime, 'average_cpu_percent':100*(usage.ru_utime+usage.ru_stime)/elapsed, 'peak_rss_mib':usage.ru_maxrss/1024, 'affinity_cpus':sorted(os.sched_getaffinity(0)), 'command':sys.argv[2:], 'thermal_units':'raw sysfs values; platform units vary by zone'}
    (output/'resources.json').write_text(json.dumps(metadata, indent=2))
print(json.dumps(metadata))
sys.exit(process.returncode)
