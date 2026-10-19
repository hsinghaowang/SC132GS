#!/usr/bin/env python3
"""Extract the installed Ubuntu source delta for CAMSS only."""
import gzip
from pathlib import Path
import sys
import re

root = Path(sys.argv[1])
text = gzip.decompress((root / 'source.diff.gz').read_bytes()).decode()
parts = re.split(r'(?m)(?=^--- linux-qcom-)', text)
selected = [part for part in parts
            if '/drivers/media/platform/qcom/camss/' in part.split('\n', 1)[0]]
(root / 'camss-ubuntu.patch').write_text(''.join(selected))
print(f'CAMSS source delta: {len(selected)} files')
