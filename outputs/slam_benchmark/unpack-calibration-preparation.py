import hashlib
from pathlib import Path
import tarfile

base=Path(__file__).resolve().parent
archive=base/'live-calibration-20261013.tar.gz'
assert hashlib.sha256(archive.read_bytes()).hexdigest()=='dfe296d665e0154005f7720b04dce2efe07029fc8afbd0eb0d8ea171ab792854'
root=(base/'live-calibration-20261013').resolve()
with tarfile.open(archive) as tar:
    for member in tar.getmembers():
        target=(root/member.name).resolve()
        assert target.is_relative_to(root) and member.isfile(), member.name
        if target.exists():
            assert hashlib.sha256(target.read_bytes()).digest()==hashlib.sha256(tar.extractfile(member).read()).digest(), 'preserve earlier evidence'
        else:tar.extract(member,path=root,filter='data')
print('Archive integrity and safe extraction passed')
