"""Check full-image equivalence on synthetic stereo cases and preserve board state."""
import json
from pathlib import Path
import subprocess
import sys

root=Path(__file__).resolve().parent
results={}
for case in ('shifted','textureless'):
    for mode in ('reference','wide'):
        label=f'verify-{case}-{mode}'
        result=subprocess.run([sys.executable,str(root/'benchmark.py'),'--case',case,
            '--mode',mode,'--label',label,'--iterations','3'],capture_output=True,text=True,timeout=90)
        if result.returncode:
            raise RuntimeError(result.stderr+result.stdout)
        report=json.loads((root/label/'benchmark.json').read_text())
        results[label]={key:report[key] for key in ('whole_image_disparity_equal_to_previous',)
                       if key in report}
        for key in ('known_12px_shift_passed','textureless_all_invalid_passed'):
            if key in report:results[label][key]=report[key]
        print(label+': passed',flush=True)
(root/'validation.json').write_text(json.dumps(results,indent=2)+'\n')
