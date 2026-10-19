"""Stage a separate candidate and source manifest; never change a live service."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import tarfile

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / 'outputs/stereo_h265_rtsp/tone-board-evidence-20261016-1420'
BOARD = '/home/ubuntu/raw10-tone-board-20261016-1420'
SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', 'ubuntu@192.168.137.226']


def main():
    global OUT, BOARD
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit-only', action='store_true', help='Create and audit a source-only archive locally, without any network access')
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--board-root', default=BOARD)
    parser.add_argument('--existing-root', action='store_true', help='Use a fresh root already containing the original backup')
    args = parser.parse_args()
    OUT, BOARD = args.out.resolve(), args.board_root
    OUT.mkdir(exist_ok=True)
    paths = []
    for name in ['stereo_h265_rtsp', 'sc132gs_v4l2_probe', 'gs130wi_imu']:
        folder = REPO / 'outputs' / name
        paths.extend(p for p in folder.iterdir() if p.is_file() and
                     (p.suffix in ['.cpp', '.hpp', '.h'] or p.name == 'CMakeLists.txt'))
    paths.extend(p for p in (REPO/'outputs/stereo_h265_rtsp/depth').iterdir()
                 if p.is_file() and p.suffix in ['.cpp', '.hpp', '.inc'])
    folder = REPO/'outputs/gs130wi_capture'
    paths.append(folder/'CMakeLists.txt')
    for sub in ['src', 'include', 'tests', 'tools']:
        paths.extend(p for p in (folder/sub).rglob('*') if p.is_file() and p.suffix in ['.cpp', '.hpp', '.h'])
    manifest = {p.relative_to(REPO).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(set(paths))}
    (OUT/'source-sha256.json').write_text(json.dumps(manifest, indent=2))
    with tarfile.open(OUT/'source.tar.gz', 'w:gz') as archive:
        for p in sorted(set(paths)):
            archive.add(p, arcname='source/'+p.relative_to(REPO).as_posix())
        archive.add(OUT/'source-sha256.json', arcname='source-sha256.json')
    with tarfile.open(OUT/'source.tar.gz') as archive:
        names = archive.getnames()
    assert set(names) == {'source/'+name for name in manifest} | {'source-sha256.json'}
    audit = dict(destination='ubuntu@192.168.137.226:'+BOARD,
                 purpose='User-requested validation on the existing camera board',
                 source_files=len(manifest), archive_bytes=(OUT/'source.tar.gz').stat().st_size,
                 contains_git_diff=False, contains_repository_metadata=False,
                 members=names, sha256=hashlib.sha256((OUT/'source.tar.gz').read_bytes()).hexdigest())
    (OUT/'upload-audit.json').write_text(json.dumps(audit, indent=2))
    print(json.dumps({k: v for k, v in audit.items() if k != 'members'}), flush=True)
    if args.audit_only:
        return
    if not args.existing_root:
        subprocess.run(SSH+['mkdir', BOARD], check=True)
    subprocess.run(['scp', str(OUT/'source.tar.gz'), 'ubuntu@192.168.137.226:'+BOARD+'/source.tar.gz'], check=True)
    code = f'''from pathlib import Path
import tarfile,json,hashlib,subprocess,os
root=Path({BOARD!r})
assert not (root/'source').exists(), 'Refuse to overwrite prior candidate source'
with tarfile.open(root/'source.tar.gz') as t:t.extractall(root,filter='data')
manifest=json.loads((root/'source-sha256.json').read_text())
assert all(hashlib.sha256((root/'source'/name).read_bytes()).hexdigest()==value for name,value in manifest.items())
os.sched_setaffinity(0,{{1,2,3}})
with (root/'build.log').open('w') as log:
 for args in [['cmake','-S',str(root/'source/outputs/stereo_h265_rtsp'),'-B',str(root/'build'),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release'],['cmake','--build',str(root/'build'),'-j','2'],['ctest','--test-dir',str(root/'build'),'--output-on-failure']]:
  p=subprocess.run(args,stdout=log,stderr=subprocess.STDOUT)
  if p.returncode:raise RuntimeError('build/test failed; see '+str(root/'build.log'))
print('CANDIDATE_BUILT',hashlib.sha256((root/'build/stereo-h265-rtsp').read_bytes()).hexdigest(),flush=True)
'''
    result = subprocess.run(SSH+['python3', '-u', '-'], input=code, text=True,
                            capture_output=True, timeout=600)
    (OUT/'stage-result.txt').write_text(result.stdout+result.stderr)
    print(result.stdout, end='')
    if result.returncode:
        print(result.stderr)
        raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
