import hashlib
from pathlib import Path
import tarfile

base=Path(__file__).resolve().parent
archive=base/'delivery-repair-20261013.tar.gz'
assert hashlib.sha256(archive.read_bytes()).hexdigest()=='cd16226eb3fd6ea85b3f0a39e1f68d222ac2450417ab3da0f7f4296e6312aa99'
root=(base/'ros-results').resolve()
with tarfile.open(archive) as tar:
    for member in tar.getmembers():
        resolved=(root/member.name).resolve()
        assert resolved.is_relative_to(root) and (member.isfile() or member.isdir()), member.name
        assert not resolved.exists(), 'Do not overwrite previously copied delivery evidence'
    tar.extractall(root,filter='data')
print('Verified archive and extracted delivery evidence')
