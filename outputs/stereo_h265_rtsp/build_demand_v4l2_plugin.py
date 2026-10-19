"""Build the exact installed QCOM V4L2 plugin with the pool-reference fix.
Run on board as an ordinary user, with archives and meson wheel in task root.
No system installation. The service selects this plugin with GST_PLUGIN_PATH.
"""
from pathlib import Path
import hashlib,json,os,subprocess,tarfile,zipfile
ROOT=Path(__file__).resolve().parent
ORIG='gst-plugins-qcom-good1.0_1.24.2.orig.tar.gz'
DEBIAN='gst-plugins-qcom-good1.0_1.24.2-qc2~1ubuntu2.debian.tar.xz'
for name,digest in [(ORIG,'23daec8eaba9bcc39106afd2b591c4abe1d9076846d082fbced4656ac7c5f6fe'),(DEBIAN,'79492dc814a165b3cdbf8643fe40c38e4a5cb83c9da9bafa56a6a7a1adaa6e80')]:
 assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest
VENDOR=ROOT/'vendor';VENDOR.mkdir(exist_ok=False)
with tarfile.open(ROOT/ORIG) as t:t.extractall(VENDOR,filter='data')
SOURCE=VENDOR/'gst-plugins-qcom-good1.0-1.24.2'
with tarfile.open(ROOT/DEBIAN) as t:t.extractall(SOURCE,filter='data')
for line in (SOURCE/'debian/patches/series').read_text().splitlines():
 if line.startswith('qcom/'):
  subprocess.run(['patch','-p1','-i',str(SOURCE/'debian/patches'/line)],cwd=SOURCE,check=True)
subprocess.run(['patch','-p1','-i',str(ROOT/'qcom-v4l2-pool-unref.patch')],cwd=SOURCE,check=True)
assert hashlib.sha256((ROOT/'meson-1.5.2-py3-none-any.whl').read_bytes()).hexdigest()=='77706e2368a00d789c097632ccf4fc39251fba56d03e1e1b262559a3c7a08f5b'
TOOLS=ROOT/'meson';TOOLS.mkdir()
with zipfile.ZipFile(ROOT/'meson-1.5.2-py3-none-any.whl') as z:z.extractall(TOOLS)
env=dict(os.environ,PYTHONPATH=str(TOOLS))
BUILD=ROOT/'plugin-build'
subprocess.run(['python3','-m','mesonbuild.mesonmain','setup',str(BUILD),str(SOURCE),'--buildtype=release','--auto-features=disabled','--wrap-mode=nodownload','-Dv4l2=enabled','-Dv4l2-gudev=enabled'],env=env,check=True)
subprocess.run(['ninja','-C',str(BUILD),'sys/v4l2/libgstvideo4linux2.so','-j3'],check=True)
plugin=BUILD/'sys/v4l2/libgstvideo4linux2.so'
(ROOT/'plugin-build.json').write_text(json.dumps(dict(plugin=str(plugin),sha256=hashlib.sha256(plugin.read_bytes()).hexdigest(),patch_sha256=hashlib.sha256((ROOT/'qcom-v4l2-pool-unref.patch').read_bytes()).hexdigest()),indent=2))
