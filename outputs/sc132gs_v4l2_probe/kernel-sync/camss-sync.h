/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef CAMSS_SC132GS_SYNC_H
#define CAMSS_SC132GS_SYNC_H
#include <linux/types.h>
struct camss;
struct csid_device;
struct vfe_line;
struct camss_buffer;
struct camss_video;
struct camss_sync;
int camss_sync_init(struct camss *camss);
void camss_sync_remove(struct camss *camss);
int camss_sync_bind(struct vfe_line *line);
void camss_sync_unbind(struct vfe_line *line);
void camss_sync_stream_started(struct camss_video *video);
bool camss_sync_observes(struct csid_device *csid, unsigned int rdi);
void camss_sync_sof(struct csid_device *csid, unsigned int rdi, u64 hw_sof);
bool camss_sync_done(struct vfe_line *line, struct camss_buffer *buffer, u64 done_ns);
#endif
