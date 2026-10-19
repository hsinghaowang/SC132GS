#!/usr/bin/env python3
"""Emit a reviewable delta against the exact guarded board source."""
import difflib
from pathlib import Path
import tarfile
root = Path(__file__).resolve().parent
patch = []
names = ('Makefile', 'camss.h', 'camss.c', 'camss-csid-gen2.c',
         'camss-vfe-17x.c', 'camss-vfe.c', 'camss-video.c',
         'camss-sync.c', 'camss-sync.h', 'camss-sync-match.h')
with tarfile.open(root/'camss-baseline.tar.gz') as archive:
    for name in names:
        try: original = archive.extractfile('./'+name).read().decode().splitlines(True)
        except KeyError: original = []
        updated = (root/name).read_text().splitlines(True)
        patch.extend(difflib.unified_diff(original, updated, fromfile='a/'+name if original else '/dev/null', tofile='b/'+name))
(root/'camss-6.8.0-1084-fsync.patch').write_text(''.join(patch), newline='\n')
print('Wrote exact guarded-source patch')
