#!/usr/bin/env python3
"""Apply synchronization hooks to the saved, geometry-guarded exact source."""
from pathlib import Path
import sys

root = Path(sys.argv[1])
def edit(name, old, new):
    p = root / name
    text = p.read_text()
    if text.count(old) != 1:
        raise SystemExit(f'{name}: expected one anchor: {old!r}')
    p.write_text(text.replace(old, new, 1))

edit('Makefile', '\t\tcamss.o \\\n', '\t\tcamss.o \\\n\t\tcamss-sync.o \\\n')
edit('camss.h', 'struct camss {', 'struct camss_sync;\n\nstruct camss {\n\tstruct camss_sync *sync;')
for name in ('camss.c', 'camss-csid-gen2.c', 'camss-vfe-17x.c'):
    edit(name, '#include "camss.h"', '#include "camss.h"\n#include "camss-sync.h"')
edit('camss.c', '\tret = camss_icc_get(camss);', '\tret = camss_sync_init(camss);\n\tif (ret)\n\t\treturn ret;\n\n\tret = camss_icc_get(camss);')
edit('camss.c', '\tv4l2_async_nf_unregister(&camss->notifier);', '\tcamss_sync_remove(camss);\n\tv4l2_async_nf_unregister(&camss->notifier);')
edit('camss.c', 'struct media_entity *camss_find_sensor(struct media_entity *entity)\n{\n\tstruct media_pad *pad;\n\n\twhile (1) {',
     'struct media_entity *camss_find_sensor(struct media_entity *entity)\n{\n\tstruct media_pad *pad;\n\n\twhile (1) {\n'
     '\t\t/* udev can open the first video node before later entities have pads. */\n'
     '\t\tif (!entity || !entity->num_pads || !entity->pads)\n\t\t\treturn NULL;')
edit('camss-csid-gen2.c', '#define CSID_RDI_CTRL(rdi)',
     '#define CSID_RDI_SOF_LO(rdi) ((csid_is_lite(csid) ? 0x290 : 0x390) + 0x100 * (rdi))\n'
     '#define CSID_RDI_SOF_HI(rdi) (CSID_RDI_SOF_LO(rdi) + 4)\n'
     '#define CSID_RDI_INPUT_SOF BIT(12)\n\n#define CSID_RDI_CTRL(rdi)')
edit('camss-csid-gen2.c', '\twritel_relaxed(val, csid->base + CSID_RDI_CFG0(vc));\n\n\t/* CSID_TIMESTAMP',
     '\twritel_relaxed(val, csid->base + CSID_RDI_CFG0(vc));\n'
     '\tif (camss_sync_observes(csid, vc)) {\n'
     '\t\twritel_relaxed(CSID_RDI_INPUT_SOF, csid->base + CSID_CSI2_RDIN_IRQ_CLEAR(vc));\n'
     '\t\twritel_relaxed(enable ? CSID_RDI_INPUT_SOF : 0, csid->base + CSID_CSI2_RDIN_IRQ_MASK(vc));\n'
     '\t\twritel_relaxed(BIT(IRQ_CMD_CLEAR), csid->base + CSID_IRQ_CMD);\n'
     '\t}\n\n\t/* CSID_TIMESTAMP')
edit('camss-csid-gen2.c', '\t\t\twritel_relaxed(val, csid->base + CSID_CSI2_RDIN_IRQ_CLEAR(i));',
     '\t\t\tif ((val & CSID_RDI_INPUT_SOF) && camss_sync_observes(csid, i)) {\n'
     '\t\t\t\tu32 hi, lo, hi2;\n'
     '\t\t\t\tdo {\n'
     '\t\t\t\t\thi = readl_relaxed(csid->base + CSID_RDI_SOF_HI(i));\n'
     '\t\t\t\t\tlo = readl_relaxed(csid->base + CSID_RDI_SOF_LO(i));\n'
     '\t\t\t\t\thi2 = readl_relaxed(csid->base + CSID_RDI_SOF_HI(i));\n'
     '\t\t\t\t} while (hi != hi2);\n'
     '\t\t\t\tcamss_sync_sof(csid, i, ((u64)hi << 32) | lo);\n'
     '\t\t\t}\n'
     '\t\t\twritel_relaxed(val, csid->base + CSID_CSI2_RDIN_IRQ_CLEAR(i));')
edit('camss-vfe-17x.c', '\tret = vfe_enable_output(line);',
     '\tret = camss_sync_bind(line);\n\tif (ret < 0)\n\t\tgoto error_enable_output;\n\n\tret = vfe_enable_output(line);')
edit('camss-vfe-17x.c',
     '\t\tif (status0 & BIT(9))\n\t\t\tif (vfe_bus_status[1] & STATUS1_WM_CLIENT_BUF_DONE(wm))\n\t\t\t\tvfe->isr_ops.wm_done(vfe, wm);',
     '\t\tif (vfe_bus_status[1] & STATUS1_WM_CLIENT_BUF_DONE(wm))\n\t\t\tvfe->isr_ops.wm_done(vfe, wm);')
edit('camss-vfe-17x.c', 'error_enable_output:\n\tvfe_put_output(line);',
     'error_enable_output:\n\tcamss_sync_unbind(line);\n\tvfe_put_output(line);')
edit('camss-vfe-17x.c', '\tu64 ts = ktime_get_ns();', '\tu64 ts = ktime_get_ns();\n\tbool sync_valid;')
edit('camss-vfe-17x.c', '\tready_buf->vb.sequence = output->sequence++;',
     '\tready_buf->vb.sequence = output->sequence++;\n\tsync_valid = camss_sync_done(line, ready_buf, ts);')
edit('camss-vfe-17x.c', '\tvb2_buffer_done(&ready_buf->vb.vb2_buf, VB2_BUF_STATE_DONE);',
     '\tvb2_buffer_done(&ready_buf->vb.vb2_buf, sync_valid ? VB2_BUF_STATE_DONE : VB2_BUF_STATE_ERROR);')
# Detach after VFE stop has synchronized its output, before releasing buffers.
edit('camss-video.c', '#include "camss-video.h"', '#include "camss-video.h"\n#include "camss-sync.h"\n#include "camss-vfe.h"')
# vfe_disable is shared by the 480 path; identify line from the owning subdev.
edit('camss-vfe.c', '#include "camss.h"', '#include "camss.h"\n#include "camss-sync.h"')
edit('camss-vfe.c', '\t\tret = vfe->res->hw_ops->vfe_disable(line);',
     '\t\tret = vfe->res->hw_ops->vfe_disable(line);\n\t\tcamss_sync_unbind(line);')

edit('camss-video.c', '\treturn 0;\n\nerror:\n\tvideo_device_pipeline_stop(vdev);', '\tcamss_sync_stream_started(video);\n\treturn 0;\n\nerror:\n\tvideo_device_pipeline_stop(vdev);')
