import hashlib
import json
from pathlib import Path

root = Path('/home/ubuntu/capture-api-20261015')
manifest = json.loads((root / 'source-sha256.json').read_text())
checked = {}
for name, expected in manifest.items():
    path = Path(name)
    if path.suffix not in ('.cpp', '.hpp', '.h', '.msg', '.xml') and path.name != 'CMakeLists.txt':
        continue
    actual = root / path
    checked[name] = actual.exists() and hashlib.sha256(actual.read_bytes()).hexdigest() == expected
(root / 'source-check.json').write_text(json.dumps(checked, indent=2) + '\n')
print(f'{sum(checked.values())}/{len(checked)} source hashes match')
raise SystemExit(0 if checked and all(checked.values()) else 1)
