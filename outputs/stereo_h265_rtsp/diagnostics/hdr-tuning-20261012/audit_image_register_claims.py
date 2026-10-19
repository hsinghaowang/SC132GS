"""Read-only audit of registers mentioned in the supplied HDR advice image.

I2C writes below select a register address for reading; no register values are
written. The live camera service, exposure policy and persistent files are left
untouched. Undocumented values are recorded without assigning bit semantics.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess
from datetime import datetime, timezone

ROOT = Path('/home/ubuntu/hdr-tuning-20261012')
TABLE = ROOT / 'source/sc132gs_v4l2_probe/sc132gs-hdr-settings.h'
OUT = ROOT / 'image-register-audit-20261012.json'


def run(args):
    return subprocess.run(args, check=True, text=True, capture_output=True,
                          timeout=10).stdout.strip()


table = TABLE.read_text()
vendor = {int(address, 16): int(value, 16) for address, value in
          re.findall(r'\{(0x[0-9a-f]+),\s*(0x[0-9a-f]+)\}', table)}
selected = {address: value for address, value in vendor.items()
            if address==0x301f or 0x320c <= address <= 0x320f or
            0x3250 <= address <= 0x3255 or
            0x3600 <= address <= 0x36ff or 0x3900 <= address <= 0x39ff
            or 0x5401 <= address <= 0x54ff}
extra = (0x0100, 0x3220, 0x3222, 0x3225, 0x3640, 0x3902, 0x391d,
         0x3933, 0x3934, 0x3e03, 0x3e06, 0x3e07, 0x3e08, 0x3e09,
         0x3e10, 0x3e11, 0x3e12, 0x3e13,
         0x5001, 0x5400)
addresses = sorted(set(selected) | set(extra))
report = dict(read_only=True, utc=datetime.now(timezone.utc).isoformat(),
              vendor_table_sha256=hashlib.sha256(TABLE.read_bytes()).hexdigest(),
              caveat='Readback agreement does not prove undocumented register '
                     'semantics or image quality.',
              before=run(['sc132gs-camera', 'status']), eyes=[])
for bus, addr in ((18, '0x32'), (16, '0x30')):
    values = {}
    for address in addresses:
        result = run(['i2ctransfer', '-f', '-y', str(bus), 'w2@' + addr,
                      hex(address >> 8), hex(address & 255), 'r1'])
        values[address] = int(result, 16)
    mismatches = [dict(address=hex(address), expected=hex(value),
                       actual=hex(values[address]))
                  for address, value in selected.items()
                  if values[address] != value]
    report['eyes'].append(dict(bus=bus, address=addr,
        registers={hex(address): hex(value) for address, value in values.items()},
        compared_vendor_registers=len(selected), mismatches=mismatches,
        documented_auto_blc_enabled=bool(values[0x3902] & 0x40)))
report['after'] = run(['sc132gs-camera', 'status'])
OUT.write_text(json.dumps(report, indent=2) + '\n')
for eye in report['eyes']:
    print(eye['bus'], eye['address'], 'auto_blc',
          eye['documented_auto_blc_enabled'], 'vendor_registers',
          eye['compared_vendor_registers'], 'mismatches', eye['mismatches'],
          'extra', {hex(address): eye['registers'][hex(address)]
                    for address in extra})
print('Saved', OUT)
