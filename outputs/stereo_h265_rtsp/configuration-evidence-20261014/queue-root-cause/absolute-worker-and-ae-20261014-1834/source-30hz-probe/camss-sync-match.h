/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef CAMSS_SYNC_MATCH_H
#define CAMSS_SYNC_MATCH_H
#include <linux/types.h>
struct camss_sync_trigger { __u64 id, before, after; };
/* First absolute slot strictly after a time; never rebase the epoch. */
static inline __u64 camss_sync_future_slot(__u64 epoch, __u64 now,
		__u64 period_ns)
{
	return now < epoch ? 0 : (now - epoch) / period_ns + 1;
}
/* A DMA completion must refer to the latest finished hardware frame. If a
 * newer SOF has arrived, EOF must still precede it and identify the prior SOF.
 * Reject coalesced/missing frame events instead of consuming a guessed FIFO.
 */
static inline int camss_sync_hardware_frame(__u64 frame, __u64 current_sof,
		__u64 previous, __u64 eof)
{
	if (!frame || !current_sof || !eof || frame > eof) return 0;
	if (eof >= current_sof) return frame == current_sof;
	return frame == previous && previous < current_sof;
}
/* Returns number of eligible triggers, never guesses a candidate. Caller must
 * accept exactly one and separately enforce monotonic identity/session. */
static inline unsigned int camss_sync_match(const struct camss_sync_trigger *pulses,
		unsigned int size, __u64 sof_ns, __u64 minimum_ns, __u64 maximum_ns,
		struct camss_sync_trigger *matched)
{
	unsigned int i, count = 0;
	matched->id = 0;
	matched->before = 0;
	matched->after = 0;
	if (minimum_ns > maximum_ns) return 0;
	for (i = 0; i < size; i++) {
		const struct camss_sync_trigger *p = &pulses[i];
		__u64 delay;
		if (!p->id || sof_ns < p->before || p->before > p->after) continue;
		delay = sof_ns - p->before;
		if (delay >= minimum_ns && delay <= maximum_ns) {
			*matched = *p;
			count++;
		}
	}
	return count;
}
#endif
