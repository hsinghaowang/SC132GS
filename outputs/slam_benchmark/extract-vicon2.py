"""Extract only V2_02_medium from the downloaded mirror archive."""
import shutil
import sys
import zipfile
from pathlib import Path

root=Path(sys.argv[1]).resolve()
with zipfile.ZipFile(root/'vicon_room2.zip') as archive:
    candidates=[n for n in archive.namelist() if Path(n).name=='V2_02_medium.zip']
    if len(candidates)!=1:
        raise ValueError(f'Expected one raw V2_02_medium.zip, found {candidates}; inspect archive listing')
    inner=root/'V2_02_medium.zip'
    with archive.open(candidates[0]) as source, inner.open('wb') as dest:
        shutil.copyfileobj(source,dest,8*1024*1024)
target=root/'V2_02_medium'
target.mkdir(exist_ok=True)
with zipfile.ZipFile(inner) as archive:
    for name in archive.namelist():
        destination=(target/name).resolve()
        if not destination.is_relative_to(target.resolve()):
            raise ValueError('archive path escapes dataset directory')
    archive.extractall(target)
print(target)
