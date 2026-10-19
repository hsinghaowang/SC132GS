#!/usr/bin/env python3
"""Generate bounded RAW10 patch from pristine Ubuntu 6.8.0-1084.89 CAMSS.

Historical filename retained for board scripts. Production contains no test
input overrides or frame-size comparison interrupts.
"""
from pathlib import Path
import difflib
import sys

root = Path(sys.argv[1])
path = root / 'camss-csid-gen2.c'
original = path.read_text()
if 'module_param(geometry_guard' in original:
    raise SystemExit('Expected pristine source; restore saved original first')


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise SystemExit(f'Unexpected source anchor: {old!r}')
    return source.replace(old, new, 1)


source = replace_once(original, '#include <linux/of.h>', '''#include <linux/of.h>
#include <linux/moduleparam.h>

/* Opt-in: verified on the QCS6490 SC132GS packed RAW10 RDI path. */
static bool geometry_guard;
module_param(geometry_guard, bool, 0644);
MODULE_PARM_DESC(geometry_guard, "Bound packed RAW10 RDI writes to negotiated geometry");''')
source = replace_once(source, '#define CSID_RDI_CFG1(rdi)', '''#define CSID_RDI_HCROP(rdi) ((csid_is_lite(csid) ? 0x21c : 0x31c) + 0x100 * (rdi))
#define CSID_RDI_VCROP(rdi) ((csid_is_lite(csid) ? 0x220 : 0x320) + 0x100 * (rdi))

#define CSID_RDI_CFG1(rdi)''')
start = source.index('static void __csid_configure_rdi_stream(')
end = source.index('static void csid_configure_stream(', start)
rdi = source[start:end]
rdi = replace_once(rdi, '\tu32 val;', '''	bool bound_raw10 = READ_ONCE(geometry_guard) &&
			   format->data_type == DATA_TYPE_RAW_10BIT;
	u32 val;''')
rdi = replace_once(rdi, '\tval = 1 << RDI_CFG0_BYTE_CNTR_EN;', '''	if (bound_raw10) {
		u32 bytes = DIV_ROUND_UP(input_format->width * format->bpp * format->spp, 8);

		/* Byte transport keeps the packed RAW10 DMA layout. Inclusive crop
		 * windows bound each packet and frame to the negotiated allocation.
		 */
		writel_relaxed((bytes - 1) << 16, csid->base + CSID_RDI_HCROP(vc));
		writel_relaxed((input_format->height - 1) << 16,
			       csid->base + CSID_RDI_VCROP(vc));
	}

	val = 1 << RDI_CFG0_BYTE_CNTR_EN;''')
rdi = replace_once(rdi, '''	/* note: for non-RDI path, this should be format->decode_format */
	val |= DECODE_FORMAT_PAYLOAD_ONLY << RDI_CFG0_DECODE_FORMAT;''', '''	/* Payload-only bypasses the crop engine. RAW8 byte transport enables
	 * cropping without unpacking or truncating the RAW10 sample bits.
	 * VFE and the public media format remain packed RAW10.
	 */
	val |= (bound_raw10 ? DECODE_FORMAT_UNCOMPRESSED_8_BIT :
		DECODE_FORMAT_PAYLOAD_ONLY) << RDI_CFG0_DECODE_FORMAT;
	if (bound_raw10)
		val |= BIT(RDI_CFG0_CROP_H_EN) | BIT(RDI_CFG0_CROP_V_EN);''')
source = source[:start] + rdi + source[end:]
patch = ''.join(difflib.unified_diff(
    original.splitlines(True), source.splitlines(True),
    fromfile='a/camss-csid-gen2.c', tofile='b/camss-csid-gen2.c'))
(root / 'camss-csid-gen2.original.c').write_text(original)
(root / 'geometry-monitor.patch').write_text(patch)
path.write_text(source)
