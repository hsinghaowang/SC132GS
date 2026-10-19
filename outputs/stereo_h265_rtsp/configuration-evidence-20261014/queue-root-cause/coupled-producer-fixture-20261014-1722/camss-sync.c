// SPDX-License-Identifier: GPL-2.0-only
/* Board-specific, opt-in SC132GS trigger-reference timestamps, ABI v1.
 * Default mode is off. Mode 1 records only; mode 2 requires a measured SOF
 * delay window. GPIO write brackets are host times, not electrical timestamps.
 */
#include <linux/debugfs.h>
#include <linux/gpio/consumer.h>
#include <linux/gpio/driver.h>
#include <linux/gpio/machine.h>
#include <linux/hrtimer.h>
#include <linux/moduleparam.h>
#include <linux/of.h>
#include <linux/seq_file.h>
#include <linux/slab.h>
#include <linux/spinlock.h>
#include <linux/io.h>
#include <linux/cpu.h>
#include <linux/smp.h>
#include <clocksource/arm_arch_timer.h>
#include "camss.h"
#include "camss-csid.h"
#include "camss-vfe.h"
#include "camss-sync.h"
#include "camss-sync-match.h"

static unsigned int fsync_mode;
module_param(fsync_mode, uint, 0444);
MODULE_PARM_DESC(fsync_mode, "0=off, 1=record only, 2=validated trigger timestamps");
static unsigned int sof_min_us, sof_max_us;
module_param(sof_min_us, uint, 0444);
module_param(sof_max_us, uint, 0444);
#define PERIOD_NS 16666667ULL
#define PULSE_NS 100000ULL
#define EVENTS 8192
#define PULSES 128
#define FRAMES 32
enum sync_error { SYNC_OK, SYNC_GPIO, SYNC_NO_TRIGGER, SYNC_AMBIGUOUS,
	SYNC_DUPLICATE, SYNC_OVERFLOW, SYNC_NO_SOF, SYNC_HW_REGRESSION,
	SYNC_NOT_RUNNING, SYNC_STARVATION, SYNC_TRIGGER_GAP, SYNC_PHASE,
	SYNC_HARDWARE_FRAME };
struct frame_event { u64 trigger, timestamp, sof, hw_sof; };
struct sync_event { u64 serial, session, ns, a, b, c; u32 kind, eye, code, sequence; };
struct sync_eye {
	struct vfe_line *line;
	struct csid_device *csid;
	u32 rdi, head, count;
	u64 last_hw, last_trigger, sof_count, done_count;
	struct frame_event frames[FRAMES];
};
struct camss_sync {
	struct camss *camss;
	struct gpio_desc *gpio[2];
	struct gpio_device *gdev;
	struct hrtimer timer;
	spinlock_t lock;
	struct mutex control;
	bool running, asserted, removing;
	u64 next, pulse_end, session, pulse_id, serial, skipped, error_count;
	u32 error;
	int timer_cpu;
	struct camss_sync_trigger pulses[PULSES];
	struct sync_eye eyes[2];
	struct sync_event events[EVENTS];
	struct dentry *debug;
};

static void record(struct camss_sync *s, u32 kind, u32 eye, u64 ns,
		   u64 a, u64 b, u64 c, u32 sequence, u32 code)
{
	u64 serial = ++s->serial;
	s->events[serial % EVENTS] = (struct sync_event){serial, s->session,
		ns, a, b, c, kind, eye, code, sequence};
}
static void fail(struct camss_sync *s, enum sync_error error)
{
	if (fsync_mode == 2) s->error_count++;
	if (fsync_mode == 2 && !s->error) {
		s->error = error;
		record(s, 4, 2, ktime_get_ns(), 0, 0, 0, 0, error);
	}
}

static enum hrtimer_restart tick(struct hrtimer *timer)
{
	struct camss_sync *s = container_of(timer, struct camss_sync, timer);
	unsigned long flags;
	u64 before, after;
	int ret;
	spin_lock_irqsave(&s->lock, flags);
	if (!s->running || s->error) {
		gpiod_set_value(s->gpio[0], 1);
		gpiod_set_value(s->gpio[1], 1);
		s->running = false;
		spin_unlock_irqrestore(&s->lock, flags);
		return HRTIMER_NORESTART;
	}
	before = ktime_get_ns();
	if (before < (s->asserted ? s->pulse_end : s->next)) {
		hrtimer_set_expires(timer, ns_to_ktime(s->asserted ? s->pulse_end : s->next));
		spin_unlock_irqrestore(&s->lock, flags);
		return HRTIMER_RESTART;
	}
	if (!s->asserted) {
		unsigned long values = 0;
		ret = gpiod_set_array_value(2, s->gpio, NULL, &values);
		after = ktime_get_ns();
		if (ret) {
			s->error = SYNC_GPIO;
			s->running = false;
			gpiod_set_value(s->gpio[0], 1);
			gpiod_set_value(s->gpio[1], 1);
			spin_unlock_irqrestore(&s->lock, flags);
			return HRTIMER_NORESTART;
		}
		s->pulse_id++;
		s->pulses[s->pulse_id % PULSES] = (struct camss_sync_trigger){s->pulse_id, before, after};
		record(s, 1, 2, before, s->pulse_id, after, s->skipped, 0, 0);
		s->skipped += (before - s->next) / PERIOD_NS;
		s->asserted = true;
		s->pulse_end = after + PULSE_NS;
		hrtimer_set_expires(timer, ns_to_ktime(s->pulse_end));
	} else {
		unsigned long values = 3;
		ret = gpiod_set_array_value(2, s->gpio, NULL, &values);
		if (ret) s->error = SYNC_GPIO;
		s->asserted = false;
		after = ktime_get_ns();
		/* Rebase after the actual deassertion. Both electrical polarities
		 * get at least one period between like edges: catching up to the old
		 * phase would make SC132GS reject a trigger at its frame-rate limit.
		 */
		s->next = camss_sync_next_assertion(after, PERIOD_NS, PULSE_NS);
		record(s, 9, 2, before, s->pulse_id, after, s->pulse_end, 0, ret ? SYNC_GPIO : 0);
		hrtimer_set_expires(timer, ns_to_ktime(s->next));
	}
	spin_unlock_irqrestore(&s->lock, flags);
	return HRTIMER_RESTART;
}

static ssize_t fsync_control_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct camss *camss = dev_get_drvdata(dev);
	struct camss_sync *s = camss->sync;
	unsigned long flags;
	ssize_t n;
	spin_lock_irqsave(&s->lock, flags);
	n = sysfs_emit(buf, "abi=1 mode=%u running=%u session=%llu pulses=%llu skipped=%llu cpu=%d error=%u error_count=%llu source=fsync_host_reference\n",
		fsync_mode, s->running, s->session, s->pulse_id, s->skipped, s->timer_cpu, s->error, s->error_count);
	spin_unlock_irqrestore(&s->lock, flags);
	return n;
}
static void start_timer_on_cpu(void *data)
{
	struct camss_sync *s = data;
	hrtimer_start(&s->timer, ns_to_ktime(s->next), HRTIMER_MODE_ABS_PINNED);
}
static ssize_t fsync_control_store(struct device *dev, struct device_attribute *attr,
				  const char *buf, size_t count)
{
	struct camss_sync *s = ((struct camss *)dev_get_drvdata(dev))->sync;
	unsigned long flags;
	int ret = 0;
	mutex_lock(&s->control);
	if (s->removing) { mutex_unlock(&s->control); return -ENODEV; }
	if (sysfs_streq(buf, "stop")) {
		spin_lock_irqsave(&s->lock, flags);
		s->running = false;
		spin_unlock_irqrestore(&s->lock, flags);
		hrtimer_cancel(&s->timer);
		gpiod_set_value(s->gpio[0], 1);
		gpiod_set_value(s->gpio[1], 1);
	} else if (sysfs_streq(buf, "start")) {
		spin_lock_irqsave(&s->lock, flags);
		if (s->running || s->eyes[0].line || s->eyes[1].line) {
			ret = -EBUSY;
		} else {
			memset(s->pulses, 0, sizeof(s->pulses));
			memset(s->eyes, 0, sizeof(s->eyes));
			s->session++;
			s->pulse_id = 0;
			s->error = 0;
			s->error_count = 0;
			s->skipped = 0;
			s->asserted = false;
			s->running = true;
			s->next = ktime_get_ns() + 100000000ULL;
		}
		spin_unlock_irqrestore(&s->lock, flags);
		if (!ret) {
			cpus_read_lock();
			s->timer_cpu = cpumask_last(cpu_online_mask);
			ret = smp_call_function_single(s->timer_cpu,
					start_timer_on_cpu, s, 1);
			cpus_read_unlock();
			if (ret) {
				spin_lock_irqsave(&s->lock, flags);
				s->running = false;
				spin_unlock_irqrestore(&s->lock, flags);
			}
		}
	} else ret = -EINVAL;
	mutex_unlock(&s->control);
	return ret ? ret : count;
}
static DEVICE_ATTR_RW(fsync_control);

static int event_show(struct seq_file *file, void *unused)
{
	struct camss_sync *s = file->private;
	struct sync_event *copy;
	unsigned long flags;
	u64 end, start, i;
	copy = kvmalloc_array(EVENTS, sizeof(*copy), GFP_KERNEL);
	if (!copy) return -ENOMEM;
	spin_lock_irqsave(&s->lock, flags);
	end = s->serial;
	spin_unlock_irqrestore(&s->lock, flags);
	/* Avoid holding an IRQ-disabling lock over a half-megabyte copy. */
	for (i = 0; i < EVENTS; i += 64) {
		spin_lock_irqsave(&s->lock, flags);
		memcpy(&copy[i], &s->events[i], 64 * sizeof(*copy));
		spin_unlock_irqrestore(&s->lock, flags);
	}
	seq_puts(file, "# abi=1 serial session kind eye ns a b c sequence error\n");
	start = end >= EVENTS ? end - EVENTS + 1 : 1;
	for (i = start; i <= end; i++) {
		struct sync_event *e = &copy[i % EVENTS];
		if (e->serial != i) continue;
		seq_printf(file, "%llu %llu %u %u %llu %llu %llu %llu %u %u\n",
			e->serial, e->session, e->kind, e->eye, e->ns, e->a,
			e->b, e->c, e->sequence, e->code);
	}
	kvfree(copy);
	return 0;
}
DEFINE_SHOW_ATTRIBUTE(event);

static int match_chip(struct gpio_chip *chip, void *data)
{
	return chip->parent && chip->parent->of_node &&
		of_device_is_compatible(chip->parent->of_node, "qcom,sc7280-pinctrl");
}
static void cleanup(void *data)
{
	struct camss_sync *s = data;
	camss_sync_remove(s->camss);
	if (!IS_ERR_OR_NULL(s->gpio[1])) gpiochip_free_own_desc(s->gpio[1]);
	if (!IS_ERR_OR_NULL(s->gpio[0])) gpiochip_free_own_desc(s->gpio[0]);
	if (s->gdev) gpio_device_put(s->gdev);
}
int camss_sync_init(struct camss *camss)
{
	struct gpio_chip *chip;
	struct gpio_device *gdev;
	struct camss_sync *s;
	int ret;
	if (!fsync_mode) return 0;
	if (fsync_mode > 2 || camss->res->version != CAMSS_7280 ||
	    (fsync_mode == 2 && (!sof_max_us || sof_max_us <= sof_min_us ||
		(sof_max_us - sof_min_us) >= 8000))) return -EINVAL;
	gdev = gpio_device_find(NULL, match_chip);
	if (!gdev) return -EPROBE_DEFER;
	chip = gpio_device_get_chip(gdev);
	s = devm_kzalloc(camss->dev, sizeof(*s), GFP_KERNEL);
	if (!s) { gpio_device_put(gdev); return -ENOMEM; }
	s->gdev = gdev;
	s->camss = camss;
	s->timer_cpu = -1;
	spin_lock_init(&s->lock);
	mutex_init(&s->control);
	hrtimer_init(&s->timer, CLOCK_MONOTONIC, HRTIMER_MODE_ABS_PINNED);
	s->timer.function = tick;
	camss->sync = s;
	s->gpio[0] = gpiochip_request_own_desc(chip, 18, "sc132gs-kernel-fsync", GPIO_ACTIVE_HIGH, GPIOD_OUT_HIGH);
	if (IS_ERR(s->gpio[0])) { ret = PTR_ERR(s->gpio[0]); gpio_device_put(gdev); return ret; }
	s->gpio[1] = gpiochip_request_own_desc(chip, 19, "sc132gs-kernel-fsync", GPIO_ACTIVE_HIGH, GPIOD_OUT_HIGH);
	ret = devm_add_action_or_reset(camss->dev, cleanup, s);
	if (ret) return ret;
	if (IS_ERR(s->gpio[1])) return PTR_ERR(s->gpio[1]);
	if (gpiod_cansleep(s->gpio[0]) || gpiod_cansleep(s->gpio[1])) return -EOPNOTSUPP;
	ret = device_create_file(camss->dev, &dev_attr_fsync_control);
	if (ret) return ret;
	s->debug = debugfs_create_dir("sc132gs_sync", NULL);
	debugfs_create_file("events", 0400, s->debug, s, &event_fops);
	return 0;
}
void camss_sync_remove(struct camss *camss)
{
	struct camss_sync *s = camss->sync;
	unsigned long flags;
	if (!s) return;
	mutex_lock(&s->control);
	spin_lock_irqsave(&s->lock, flags);
	s->removing = true;
	s->running = false;
	spin_unlock_irqrestore(&s->lock, flags);
	hrtimer_cancel(&s->timer);
	if (!IS_ERR_OR_NULL(s->gpio[0])) gpiod_set_value(s->gpio[0], 1);
	if (!IS_ERR_OR_NULL(s->gpio[1])) gpiod_set_value(s->gpio[1], 1);
	mutex_unlock(&s->control);
	device_remove_file(camss->dev, &dev_attr_fsync_control);
	debugfs_remove_recursive(s->debug);
	s->debug = NULL;
}

int camss_sync_bind(struct vfe_line *line)
{
	struct camss *camss = to_vfe(line)->camss;
	struct camss_sync *s = camss->sync;
	struct media_entity *entity = &line->subdev.entity;
	struct media_pad *pad;
	struct csid_device *csid = NULL;
	unsigned long flags;
	u32 i, rdi = 0, eye;
	int ret = 0;
	if (!s) return 0;
	for (i = 0; i < 8; i++) {
		pad = media_pad_remote_pad_first(&entity->pads[0]);
		if (!pad) return -ENOLINK;
		entity = pad->entity;
		for (rdi = 0; rdi < camss->res->csid_num; rdi++)
			if (entity == &camss->csid[rdi].subdev.entity) {
				csid = &camss->csid[rdi];
				break;
			}
		if (csid) { rdi = pad->index - MSM_CSID_PAD_FIRST_SRC; break; }
	}
	if (!csid || rdi >= MSM_CSID_MAX_SRC_STREAMS) return -ENOLINK;
	if (csid->phy.csiphy_id == 1) eye = 0;
	else if (csid->phy.csiphy_id == 4) eye = 1;
	else return -EOPNOTSUPP;
	spin_lock_irqsave(&s->lock, flags);
	if (!s->running || s->error) ret = -EPIPE;
	else if (s->eyes[eye].line) ret = -EBUSY;
	else {
		s->eyes[eye] = (struct sync_eye){.line = line, .csid = csid, .rdi = rdi};
		record(s, 5, eye, ktime_get_ns(), csid->id, rdi, to_vfe(line)->id, line->id, 0);
	}
	spin_unlock_irqrestore(&s->lock, flags);
	return ret;
}
void camss_sync_unbind(struct vfe_line *line)
{
	struct camss_sync *s = to_vfe(line)->camss->sync;
	unsigned long flags;
	u32 i;
	if (!s) return;
	spin_lock_irqsave(&s->lock, flags);
	for (i = 0; i < 2; i++) if (s->eyes[i].line == line) {
		record(s, 6, i, ktime_get_ns(), 0, 0, 0, 0, 0);
		memset(&s->eyes[i], 0, sizeof(s->eyes[i]));
	}
	/* STREAMOFF ends this session. A remaining consumer gets ERROR if it
	 * continues to dequeue; an ordinary complete shutdown is not a fault.
	 */
	s->running = false;
	spin_unlock_irqrestore(&s->lock, flags);
}
bool camss_sync_observes(struct csid_device *csid, unsigned int rdi)
{
	return csid->camss->sync && !csid->testgen.enabled && rdi == 0;
}
void camss_sync_sof(struct csid_device *csid, unsigned int rdi, u64 hw_sof)
{
	struct camss_sync *s = csid->camss->sync;
	struct sync_eye *e = NULL;
	struct camss_sync_trigger found = {};
	unsigned long flags;
	u64 counter = arch_timer_read_counter();
	u64 irq_ns = ktime_get_ns();
	u64 now = irq_ns;
	u32 rate = arch_timer_get_cntfrq();
	bool mapping_valid;
	u32 i, eye = 2, matches = 0;
	if (!s) return;
	spin_lock_irqsave(&s->lock, flags);
	for (i = 0; i < 2; i++) if (s->eyes[i].csid == csid && s->eyes[i].rdi == rdi) {
		e = &s->eyes[i]; eye = i; break;
	}
	if (!e) goto out;
	/* CSID's QTimer latch and the ARM counter share the 19.2MHz timebase.
	 * Map the hardware frame event to CLOCK_MONOTONIC at the current IRQ,
	 * rather than letting IRQ scheduling jitter select another pulse.
	 */
	mapping_valid = rate == 19200000 && hw_sof && counter >= hw_sof && counter-hw_sof < rate;
	if (mapping_valid) {
		now -= div_u64((counter-hw_sof)*10000,192);
	} else fail(s, SYNC_HARDWARE_FRAME);
	record(s, 8, eye, irq_ns, now, counter, rate, e->sof_count, mapping_valid ? 0 : SYNC_HARDWARE_FRAME);
	e->sof_count++;
	if (hw_sof <= e->last_hw) fail(s, SYNC_HW_REGRESSION);
	e->last_hw = hw_sof;
	matches = camss_sync_match(s->pulses, PULSES, now,
			(u64)sof_min_us * 1000, (u64)sof_max_us * 1000, &found);
	if (matches != 1) fail(s, matches ? SYNC_AMBIGUOUS : SYNC_NO_TRIGGER);
	if (matches == 1 && found.id <= e->last_trigger) fail(s, SYNC_DUPLICATE);
	if (matches == 1 && e->last_trigger && found.id != e->last_trigger + 2)
		fail(s, SYNC_TRIGGER_GAP);
	if (matches == 1 && s->eyes[1-eye].last_trigger &&
	    ((found.id ^ s->eyes[1-eye].last_trigger) & 1)) fail(s, SYNC_PHASE);
	if (matches == 1) e->last_trigger = found.id;
	record(s, 2, eye, now, found.id, hw_sof, s->pulse_id, e->sof_count, matches != 1);
	if (e->count == FRAMES) { fail(s, SYNC_OVERFLOW); goto out; }
	e->frames[(e->head + e->count) % FRAMES] = (struct frame_event){
		.trigger = matches == 1 ? found.id : 0, .timestamp = found.after,
		.sof = now, .hw_sof = hw_sof};
	e->count++;
out:
	spin_unlock_irqrestore(&s->lock, flags);
}
static u64 read_stamp(struct csid_device *csid, u32 rdi, u32 offset)
{
	u32 base = (csid_is_lite(csid) ? 0x200 : 0x300) + rdi * 0x100 + offset;
	u32 hi, lo, again;
	do {
		hi = readl_relaxed(csid->base + base + 4);
		lo = readl_relaxed(csid->base + base);
		again = readl_relaxed(csid->base + base + 4);
	} while (hi != again);
	return ((u64)hi << 32) | lo;
}
bool camss_sync_done(struct vfe_line *line, struct camss_buffer *buffer, u64 done_ns)
{
	struct camss_sync *s = to_vfe(line)->camss->sync;
	struct sync_eye *e = NULL;
	struct frame_event frame = {};
	unsigned long flags;
	u32 i, eye = 2;
	bool valid = true;
	if (!s) return true;
	spin_lock_irqsave(&s->lock, flags);
	for (i = 0; i < 2; i++) if (s->eyes[i].line == line) { e = &s->eyes[i]; eye = i; break; }
	if (!e) { fail(s, SYNC_NO_SOF); goto out; }
	e->done_count++;
	if (!e->count) fail(s, SYNC_NO_SOF);
	else {
		frame = e->frames[e->head];
		e->head = (e->head + 1) % FRAMES; e->count--;
	}
	if (!line->output.buf[1]) fail(s, SYNC_STARVATION);
	if (!s->running || !frame.trigger) fail(s, SYNC_NO_TRIGGER);
	if (frame.hw_sof) {
		u64 current_sof = read_stamp(e->csid, e->rdi, 0x90);
		u64 previous = read_stamp(e->csid, e->rdi, 0x98);
		u64 eof = read_stamp(e->csid, e->rdi, 0xa0);
		bool hw_valid = camss_sync_hardware_frame(frame.hw_sof, current_sof, previous, eof);
		if (!hw_valid)
			fail(s, SYNC_HARDWARE_FRAME);
		record(s, 7, eye, done_ns, current_sof, previous, eof, buffer->vb.sequence, hw_valid ? 0 : SYNC_HARDWARE_FRAME);
	}
	record(s, 3, eye, done_ns, frame.trigger, frame.hw_sof, frame.sof, buffer->vb.sequence, s->error);
out:
	if (fsync_mode == 2) {
		valid = !s->error && frame.trigger;
		if (valid) buffer->vb.vb2_buf.timestamp = frame.timestamp;
	}
	spin_unlock_irqrestore(&s->lock, flags);
	return valid;
}
