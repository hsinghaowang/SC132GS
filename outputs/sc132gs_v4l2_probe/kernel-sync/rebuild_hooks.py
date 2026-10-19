#!/usr/bin/env python3
from pathlib import Path
import runpy
import sys
import tarfile
root = Path(__file__).resolve().parent
with tarfile.open(root / 'camss-baseline.tar.gz') as archive:
    for member in archive.getmembers():
        name = Path(member.name).name
        if not member.isfile() or name in ('camss-sync.c','camss-sync.h','camss-sync-match.h'):
            continue
        if name in ('Makefile','Kconfig','camss.c','camss.h') or (
                name.startswith('camss-') and name.endswith(('.c','.h'))):
            (root / name).write_bytes(archive.extractfile(member).read())
sys.argv = ['apply_sync.py', str(root)]
runpy.run_path(str(root / 'apply_sync.py'), run_name='__main__')
