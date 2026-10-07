/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SC132GS_CONTROLS_H
#define SC132GS_CONTROLS_H

/* Private controls shared by this out-of-tree driver and capture owner.
 * Standard EXPOSURE retains its legacy SECOND/4 HDR encoding.
 */
#define V4L2_CID_SC132GS_HDR_TOTAL_ROWS (V4L2_CID_USER_BASE + 0x2100)
#define V4L2_CID_SC132GS_HDR_RATIO      (V4L2_CID_USER_BASE + 0x2101)
#define SC132GS_HDR_TOTAL_DEFAULT     1492
#define SC132GS_HDR_TOTAL_MAX         1492
#define SC132GS_HDR_RATIO_DEFAULT     256

#endif
