// SPDX-License-Identifier: GPL-2.0-only
/* Board-specific, opt-in SC132GS trigger-reference timestamps, ABI v2.
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
#include <linux/pm_qos.h>
#include <linux/workqueue.h>
#include <clocksource/arm_arch_timer.h>
#include <media/v4l2-ctrls.h>
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
#define PERIOD_NS 33333333ULL
#define PULSE_NS 100000ULL
#define LATE_BUDGET_NS 100000ULL
#define EVENTS 8192
#define PULSES 128
#define FRAMES 32
#define TRIGGER_EVENTS 256
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
	u64 bind_hw, last_hw, last_trigger, sof_count, done_count;
	struct frame_event frames[FRAMES];
};
struct trigger_event { u64 before, after, id, extra; u32 kind, code; };
struct camss_sync {
	struct camss *camss;
	struct gpio_desc *gpio[2];
	struct gpio_device *gdev;
	struct hrtimer timer;
	spinlock_t lock;
	/* Producer publication never shares the frame/diagnostic lock. */
	raw_spinlock_t trigger_lock;
	struct work_struct trigger_work;
	struct trigger_event pending[TRIGGER_EVENTS];
	u32 pending_head, pending_count, trigger_error;
	struct mutex control;
	struct pm_qos_request latency;
	bool running, asserted, removing;
	u64 epoch, slot, next, pulse_end, session, pulse_id, serial, skipped, error_count;
	u64 last_assert_after, last_deassert_after;
	u32 error;
	int timer_cpu, worker_cpu;
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

/* The timer only produces actual GPIO brackets. Frame association and trace
 * formatting run independently; neither can change the absolute cadence. */
static void drain_triggers(struct work_struct *work)
{
	struct camss_sync *s = container_of(work, struct camss_sync, trigger_work);
	struct trigger_event e;
	unsigned long flags;
	for (;;) {
		raw_spin_lock_irqsave(&s->trigger_lock, flags);
		if (!s->pending_count) {
			raw_spin_unlock_irqrestore(&s->trigger_lock, flags);
			break;
		}
		e = s->pending[s->pending_head];
		s->pending_head = (s->pending_head + 1) % TRIGGER_EVENTS;
		s->pending_count--;
		raw_spin_unlock_irqrestore(&s->trigger_lock, flags);
		spin_lock_irqsave(&s->lock, flags);
		record(s, e.kind, 2, e.before, e.id, e.after, e.extra, 0, e.code);
		spin_unlock_irqrestore(&s->lock, flags);
	}
	spin_lock_irqsave(&s->lock, flags);
	if (READ_ONCE(s->trigger_error)) fail(s, READ_ONCE(s->trigger_error));
	spin_unlock_irqrestore(&s->lock, flags);
}
static void publish_trigger(struct camss_sync *s, struct trigger_event e)
{
	unsigned long flags;
	raw_spin_lock_irqsave(&s->trigger_lock, flags);
	if (e.kind == 1)
		s->pulses[e.id % PULSES] = (struct camss_sync_trigger){e.id, e.before, e.after};
	if (s->pending_count == TRIGGER_EVENTS) {
		WRITE_ONCE(s->trigger_error, SYNC_OVERFLOW);
	} else {
		s->pending[(s->pending_head + s->pending_count) % TRIGGER_EVENTS] = e;
		s->pending_count++;
	}
	raw_spin_unlock_irqrestore(&s->trigger_lock, flags);
	/* A frame-lock waiter must never mask IRQs on the timer's CPU. */
	queue_work_on(s->worker_cpu, system_wq, &s->trigger_work);
}
static enum hrtimer_restart tick(struct hrtimer *timer)
{
	struct camss_sync *s = container_of(timer, struct camss_sync, timer);
	u64 before, after, next_slot;
	unsigned long values;
	int ret;
	if (!READ_ONCE(s->running) || READ_ONCE(s->trigger_error) == SYNC_GPIO) {
		gpiod_set_value(s->gpio[0], 1);
		gpiod_set_value(s->gpio[1], 1);
		return HRTIMER_NORESTART;
	}
	before = ktime_get_ns();
	if (before < (s->asserted ? s->pulse_end : s->next)) {
		hrtimer_set_expires(timer, ns_to_ktime(s->asserted ? s->pulse_end : s->next));
		return HRTIMER_RESTART;
	}
	if (!s->asserted) {
		/* Admit only bounded lateness and conservative same-polarity
		 * bracket spacing. A delayed deassertion must not shorten the next
		 * rising-edge interval either. GPIO duration is never a new epoch. */
		if (before - s->next > LATE_BUDGET_NS ||
		    (s->last_assert_after && before - s->last_assert_after < PERIOD_NS - LATE_BUDGET_NS) ||
		    (s->last_deassert_after && before + PULSE_NS - s->last_deassert_after < PERIOD_NS - LATE_BUDGET_NS)) {
			next_slot = camss_sync_future_slot(s->epoch, before, PERIOD_NS);
			publish_trigger(s, (struct trigger_event){before, before, s->slot + 1, s->next, 10, SYNC_TRIGGER_GAP});
			s->skipped += next_slot - s->slot;
			s->slot = next_slot;
			s->next = s->epoch + s->slot * PERIOD_NS;
			hrtimer_set_expires(timer, ns_to_ktime(s->next));
			return HRTIMER_RESTART;
		}
		values = 0;
		ret = gpiod_set_array_value(2, s->gpio, NULL, &values);
		after = ktime_get_ns();
		if (ret) {
			WRITE_ONCE(s->trigger_error, SYNC_GPIO);
			gpiod_set_value(s->gpio[0], 1);
			gpiod_set_value(s->gpio[1], 1);
			publish_trigger(s, (struct trigger_event){before, after, s->slot + 1, 0, 4, SYNC_GPIO});
			return HRTIMER_NORESTART;
		}
		s->pulse_id = s->slot + 1;
		s->last_assert_after = after;
		s->asserted = true;
		s->pulse_end = after + PULSE_NS;
		publish_trigger(s, (struct trigger_event){before, after, s->pulse_id, s->skipped, 1, 0});
		hrtimer_set_expires(timer, ns_to_ktime(s->pulse_end));
	} else {
		values = 3;
		ret = gpiod_set_array_value(2, s->gpio, NULL, &values);
		after = ktime_get_ns();
		s->asserted = false;
		s->last_deassert_after = after;
		if (ret) WRITE_ONCE(s->trigger_error, SYNC_GPIO);
		publish_trigger(s, (struct trigger_event){before, after, s->pulse_id, s->pulse_end, 9, ret ? SYNC_GPIO : 0});
		/* Fixed epoch: GPIO duration and worker latency never accumulate drift.
		 * If late, skip to a future slot with at least half a period of idle. */
		next_slot = camss_sync_future_slot(s->epoch, after + PERIOD_NS / 2, PERIOD_NS);
		if (next_slot < s->slot + 1) next_slot = s->slot + 1;
		s->skipped += next_slot - s->slot - 1;
		s->slot = next_slot;
		s->next = s->epoch + s->slot * PERIOD_NS;
		hrtimer_set_expires(timer, ns_to_ktime(s->next));
	}
	return HRTIMER_RESTART;
}

static ssize_t fsync_control_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct camss *camss = dev_get_drvdata(dev);
	struct camss_sync *s = camss->sync;
	unsigned long flags;
	ssize_t n;
	spin_lock_irqsave(&s->lock, flags);
	n = sysfs_emit(buf, "abi=2 trigger_hz=30 frame_step=1 mode=%u running=%u session=%llu pulses=%llu skipped=%llu cpu=%d worker_cpu=%d error=%u error_count=%llu source=fsync_host_reference\n",
		fsync_mode, s->running, s->session, s->pulse_id, s->skipped, s->timer_cpu, s->worker_cpu, s->error ? s->error : READ_ONCE(s->trigger_error), s->error_count);
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
		flush_work(&s->trigger_work);
		if (cpu_latency_qos_request_active(&s->latency))
			cpu_latency_qos_remove_request(&s->latency);
		gpiod_set_value(s->gpio[0], 1);
		gpiod_set_value(s->gpio[1], 1);
	} else if (sysfs_streq(buf, "start")) {
		spin_lock_irqsave(&s->lock, flags);
		if (s->running || s->eyes[0].line || s->eyes[1].line) {
			ret = -EBUSY;
		} else {
			raw_spin_lock(&s->trigger_lock);
			memset(s->pulses, 0, sizeof(s->pulses));
			s->pending_head = s->pending_count = 0;
			s->trigger_error = 0;
			raw_spin_unlock(&s->trigger_lock);
			memset(s->eyes, 0, sizeof(s->eyes));
			s->session++;
			s->pulse_id = 0;
			s->error = 0;
			s->error_count = 0;
			s->skipped = 0;
			s->asserted = false;
			s->last_assert_after = s->last_deassert_after = 0;
			s->running = true;
			s->epoch = ktime_get_ns() + 100000000ULL;
			s->slot = 0;
			s->next = s->epoch;
		}
		spin_unlock_irqrestore(&s->lock, flags);
		if (!ret) {
			if (!cpu_latency_qos_request_active(&s->latency))
				cpu_latency_qos_add_request(&s->latency, 50);
			cpus_read_lock();
			s->timer_cpu = cpumask_last(cpu_online_mask);
			s->worker_cpu = cpumask_first(cpu_online_mask);
			if (s->worker_cpu == s->timer_cpu)
				ret = -EOPNOTSUPP;
			else
				ret = smp_call_function_single(s->timer_cpu,
						start_timer_on_cpu, s, 1);
			cpus_read_unlock();
			if (ret) {
				spin_lock_irqsave(&s->lock, flags);
				s->running = false;
				spin_unlock_irqrestore(&s->lock, flags);
				cpu_latency_qos_remove_request(&s->latency);
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
	seq_puts(file, "# abi=2 serial session kind eye ns a b c sequence error\n");
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
		(u64)(sof_max_us - sof_min_us) * 1000 >= PERIOD_NS - LATE_BUDGET_NS))) return -EINVAL;
	gdev = gpio_device_find(NULL, match_chip);
	if (!gdev) return -EPROBE_DEFER;
	chip = gpio_device_get_chip(gdev);
	s = devm_kzalloc(camss->dev, sizeof(*s), GFP_KERNEL);
	if (!s) { gpio_device_put(gdev); return -ENOMEM; }
	s->gdev = gdev;
	s->camss = camss;
	s->timer_cpu = -1;
	s->worker_cpu = -1;
	spin_lock_init(&s->lock);
	raw_spin_lock_init(&s->trigger_lock);
	INIT_WORK(&s->trigger_work, drain_triggers);
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
		flush_work(&s->trigger_work);
	if (cpu_latency_qos_request_active(&s->latency))
		cpu_latency_qos_remove_request(&s->latency);
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
	struct media_entity *sensor_entity;
	struct v4l2_subdev *sensor;
	struct v4l2_ctrl *hdr, *exposure;
	struct v4l2_subdev_format format = {.which = V4L2_SUBDEV_FORMAT_ACTIVE, .pad = 0};
	unsigned long flags;
	u32 i, rdi = 0, eye;
	int ret = 0;
	if (!s) return 0;
	/* The calibrated latency is valid only for this full Linear profile.
	 * SC132GS itself rejects HDR/layout changes while streaming. Its linear
	 * exposure ceiling is below one 30Hz period; uncalibrated settings must
	 * yield no candidate, never an adjacent trigger alias. */
	sensor_entity = camss_find_sensor(entity);
	if (!sensor_entity) return -ENOLINK;
	sensor = media_entity_to_v4l2_subdev(sensor_entity);
	if (strncmp(sensor->name, "sc132gs", 7) || !sensor->ctrl_handler)
		return -EOPNOTSUPP;
	hdr = v4l2_ctrl_find(sensor->ctrl_handler, V4L2_CID_WIDE_DYNAMIC_RANGE);
	exposure = v4l2_ctrl_find(sensor->ctrl_handler, V4L2_CID_EXPOSURE);
	if (!hdr || !exposure || v4l2_ctrl_g_ctrl(hdr) ||
	    exposure->minimum != 8 || exposure->maximum > 2560)
		return -EOPNOTSUPP;
	ret = v4l2_subdev_call(sensor, pad, get_fmt, NULL, &format);
	if (ret || format.format.width != 1088 || format.format.height != 1280 ||
	    format.format.code != MEDIA_BUS_FMT_SRGGB10_1X10)
		return ret ? ret : -EOPNOTSUPP;
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
	if (!s->running || s->error || READ_ONCE(s->trigger_error)) ret = -EPIPE;
	else if (s->eyes[eye].line) ret = -EBUSY;
	else {
		s->eyes[eye] = (struct sync_eye){.line = line, .csid = csid, .rdi = rdi,
			.bind_hw = arch_timer_read_counter()};
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
	mutex_lock(&s->control);
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
	hrtimer_cancel(&s->timer);
		flush_work(&s->trigger_work);
	if (cpu_latency_qos_request_active(&s->latency))
		cpu_latency_qos_remove_request(&s->latency);
	gpiod_set_value(s->gpio[0], 1);
	gpiod_set_value(s->gpio[1], 1);
	mutex_unlock(&s->control);
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
	/* A retained CSID latch can predate this graph binding. It belongs to
	 * an old session and cannot identify any current DMA buffer. */
	if (hw_sof < e->bind_hw) {
		record(s, 12, eye, irq_ns, hw_sof, e->bind_hw, 0, 0, 0);
		goto out;
	}
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
	/* Copy one immutable trigger at a time; no long producer lock or
	 * shared diagnostic lock can postpone the electrical edge. */
	for (i = 0; i < PULSES; i++) {
		struct camss_sync_trigger pulse, candidate;
		raw_spin_lock(&s->trigger_lock);
		pulse = s->pulses[i];
		raw_spin_unlock(&s->trigger_lock);
		if (camss_sync_match(&pulse, 1, now, (u64)sof_min_us * 1000,
			(u64)sof_max_us * 1000, &candidate)) {
			found = candidate;
			matches++;
		}
	}
	if (matches != 1) fail(s, matches ? SYNC_AMBIGUOUS : SYNC_NO_TRIGGER);
	if (matches == 1 && found.id <= e->last_trigger) fail(s, SYNC_DUPLICATE);
	if (matches == 1 && e->last_trigger && found.id != e->last_trigger + 1)
		fail(s, SYNC_TRIGGER_GAP);
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
		valid = !s->error && !READ_ONCE(s->trigger_error) && frame.trigger;
		if (valid) buffer->vb.vb2_buf.timestamp = frame.timestamp;
	}
	spin_unlock_irqrestore(&s->lock, flags);
	return valid;
}
