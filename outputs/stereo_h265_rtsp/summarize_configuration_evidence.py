import json
from pathlib import Path

root = Path(__file__).parent / 'configuration-evidence-20261007'
rows = []
for source in sorted(root.glob('*/decode.json'), key=lambda p: p.stat().st_mtime):
    value = json.loads(source.read_text())
    request_path = source.parent / 'request.json'
    rows.append(dict(directory=source.parent.name,
                     request=json.loads(request_path.read_text()) if request_path.exists() else None,
                     width=value['width'], height=value['height'],
                     decoded_frames=value['decoded_frames'], pts_fps=value['pts_fps']))
(root / 'manifest.json').write_text(json.dumps(rows,indent=2))
print(json.dumps(rows,indent=2))
