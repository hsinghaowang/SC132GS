#!/usr/bin/env python3
"""Backport the reviewed VFE-17x buffer-done fix to exact Ubuntu 1084 source."""
import difflib
import hashlib
from pathlib import Path
import sys

root = Path(sys.argv[1])
path = root / 'camss-vfe-17x.c'
blob = path.read_bytes()
if hashlib.sha256(blob).hexdigest() != '25fafad7e739bf1bffa8fad97c9a4414b309ab29ad7066e17c7471cf76f727f8':
    raise SystemExit('Expected pristine Ubuntu 6.8.0-1084.89 VFE-17x source')
original = blob.decode()
old = '''	for (wm = 0; wm < MSM_VFE_IMAGE_MASTERS_NUM; wm++)
		if (status0 & BIT(9))
			if (vfe_bus_status[1] & STATUS1_WM_CLIENT_BUF_DONE(wm))
				vfe->isr_ops.wm_done(vfe, wm);'''
new = '''	for (wm = 0; wm < MSM_VFE_IMAGE_MASTERS_NUM; wm++)
		if (vfe_bus_status[1] & STATUS1_WM_CLIENT_BUF_DONE(wm))
			vfe->isr_ops.wm_done(vfe, wm);'''
if original.count(old) != 1:
    raise SystemExit('Unexpected ISR layout')
fixed = original.replace(old, new, 1)
backup = root / 'camss-vfe-17x.before-done-fix.c'
if backup.exists() and backup.read_bytes() != blob:
    raise SystemExit('Existing VFE backup differs; preserve and inspect it first')
backup.write_bytes(blob)
path.write_bytes(fixed.encode())
patch = ''.join(difflib.unified_diff(original.splitlines(True), fixed.splitlines(True),
    fromfile='a/camss-vfe-17x.c', tofile='b/camss-vfe-17x.c'))
(root / 'vfe-done.patch').write_text(patch)
print(patch, end='')
