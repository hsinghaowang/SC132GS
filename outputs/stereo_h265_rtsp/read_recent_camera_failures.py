from pathlib import Path
roots=sorted(Path('/home/ubuntu/sc132gs-camera-tests').glob('failure-*'),key=lambda p:p.stat().st_mtime)
for root in roots[-3:]:
    print(root)
    print((root/'request.json').read_text())
    print((root/'server.log').read_text()[-8000:])
logs=sorted(Path('/home/ubuntu/sc132gs-camera-tests/startup-logs').glob('*.log'),key=lambda p:p.stat().st_mtime)
for log in logs[-2:]:
    print(log)
    print(log.read_text()[-8000:])
