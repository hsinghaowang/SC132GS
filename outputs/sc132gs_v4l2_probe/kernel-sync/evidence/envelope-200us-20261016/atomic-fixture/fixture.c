
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint64_t u64; typedef uint64_t __u64; typedef uint32_t u32;
#define PERIOD_NS 33333333ULL
#define PULSE_NS 100000ULL
#define LATE_BUDGET_NS 500000ULL
#define PULSE_OVERRUN_NS 25000ULL
#define PULSE_ENVELOPE_NS 200000ULL
#define SYNC_TRIGGER_GAP 10
#define SYNC_GPIO 1
#define SYNC_PULSE_WIDTH 14
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
enum hrtimer_restart { HRTIMER_NORESTART,HRTIMER_RESTART };
struct hrtimer {u64 expires;}; struct gpio_desc {int x;};
struct trigger_event {u64 before,after,id,extra;u32 kind,code;};
struct camss_sync {struct hrtimer timer;struct gpio_desc *gpio[2];bool running,asserted;
u64 epoch,slot,next,pulse_end,pulse_id,skipped,last_assert_after,last_deassert_after;u32 trigger_error,error;};
static u64 now,asserts,releases,last_assert,last_release,gpio_cost,high_gpio_cost,pending_irq_delay;
static int gpio_error,irq_held,fail_release;
static unsigned low_records,high_records,gap_records;
static void require(bool value){if(!value)abort();}
static u64 ktime_get_ns(void){return now;}
static void cpu_relax(void){now+=100;if(!irq_held&&pending_irq_delay){now+=pending_irq_delay;pending_irq_delay=0;}}
#define local_irq_save(f) do{require(!irq_held);(f)=0;irq_held=1;}while(0)
#define local_irq_restore(f) do{(void)(f);require(irq_held);irq_held=0;}while(0)
static u64 ns_to_ktime(u64 value){return value;}
static void hrtimer_set_expires(struct hrtimer *timer,u64 value){timer->expires=value;}
static void gpiod_set_value(struct gpio_desc *gpio,int value){(void)gpio;(void)value;}
static int gpiod_set_array_value(int count,struct gpio_desc **gpio,void *info,unsigned long *values){
(void)gpio;(void)info;require(count==2&&irq_held);
if(!*values){asserts++;last_assert=now;}else{releases++;last_release=now;}
now+=*values?high_gpio_cost:gpio_cost;return (*values&&fail_release)?-5:gpio_error;}
static void publish_trigger(struct camss_sync *sync,struct trigger_event event){
(void)sync;require(!irq_held&&event.after>=event.before);
if(event.kind==1){low_records++;}
if(event.kind==9){high_records++;}
if(event.kind==10){gap_records++;}}
static inline __u64 camss_sync_future_slot(__u64 epoch, __u64 now,
		__u64 period_ns)
{
	return now < epoch ? 0 : (now - epoch) / period_ns + 1;
}
static inline __u64 camss_sync_earliest_edge(__u64 deadline, __u64 last_low_after,
		__u64 last_high_after, __u64 minimum_period, __u64 pulse_ns)
{
	__u64 next = deadline;
	if (last_low_after && last_low_after + minimum_period > next)
		next = last_low_after + minimum_period;
	if (last_high_after && last_high_after + minimum_period > next + pulse_ns)
		next = last_high_after + minimum_period - pulse_ns;
	return next;
}
static enum hrtimer_restart tick(struct hrtimer *timer)
{
	struct camss_sync *s = container_of(timer, struct camss_sync, timer);
	u64 before, after, rise_before, rise_after, next_slot, earliest;
	unsigned long values, flags;
	int ret;
	if (!READ_ONCE(s->running) || READ_ONCE(s->trigger_error) == SYNC_GPIO) {
		gpiod_set_value(s->gpio[0], 1);
		gpiod_set_value(s->gpio[1], 1);
		return HRTIMER_NORESTART;
	}
	/* Keep the entire short pulse in one hard callback. Two separately
	 * scheduled edges allowed a late release to move the sensor frame
	 * outside its measured window, then shorten the next rising interval.
	 * GPIO cannot sleep (checked at probe). No workqueue/frame lock is
	 * touched while the pulse is asserted; 100us * 30Hz is 0.3% of one CPU.
	 */
	local_irq_save(flags);
	before = ktime_get_ns();
	earliest = camss_sync_earliest_edge(s->next, s->last_assert_after,
		s->last_deassert_after, PERIOD_NS - LATE_BUDGET_NS, PULSE_NS);
	if (before < earliest) {
		local_irq_restore(flags);
		hrtimer_set_expires(timer, ns_to_ktime(earliest));
		return HRTIMER_RESTART;
	}
	/* Bounded start jitter is safe only while the full characterized
	 * exposure/readout fits before the earliest following slot. The
	 * mode-2 probe gate checks that margin; never emit a catch-up pulse.
	 */
	if (before - s->next > LATE_BUDGET_NS) {
		local_irq_restore(flags);
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
		local_irq_restore(flags);
		publish_trigger(s, (struct trigger_event){before, after, s->slot + 1, 0, 4, SYNC_GPIO});
		return HRTIMER_NORESTART;
	}
	s->pulse_id = s->slot + 1;
	s->last_assert_after = after;
	s->pulse_end = after + PULSE_NS;
	while (ktime_get_ns() < s->pulse_end) cpu_relax();
	rise_before = ktime_get_ns();
	values = 3;
	ret = gpiod_set_array_value(2, s->gpio, NULL, &values);
	rise_after = ktime_get_ns();
	s->last_deassert_after = rise_after;
	if (ret) WRITE_ONCE(s->trigger_error, SYNC_GPIO);
	/* Independent bounds: total host envelope 200us, release overrun 25us. */
	else if (rise_after - before > PULSE_ENVELOPE_NS ||
		 rise_after - s->pulse_end > PULSE_OVERRUN_NS)
		WRITE_ONCE(s->trigger_error, SYNC_PULSE_WIDTH);
	local_irq_restore(flags);
	/* Publish the low reference unchanged, before any characterized SOF
	 * can occur (minimum >100us pulse plus bounded GPIO completion).
	 */
	publish_trigger(s, (struct trigger_event){before, after, s->pulse_id, s->skipped, 1, 0});
	publish_trigger(s, (struct trigger_event){rise_before, rise_after, s->pulse_id,
		s->pulse_end, 9, READ_ONCE(s->trigger_error)});
	if (READ_ONCE(s->trigger_error)) return HRTIMER_NORESTART;
	/* No drift: only the absolute epoch selects the next slot. */
	next_slot = camss_sync_future_slot(s->epoch, rise_after + PERIOD_NS / 2, PERIOD_NS);
	if (next_slot < s->slot + 1) next_slot = s->slot + 1;
	if (next_slot > s->slot + 1) {
		s->skipped += next_slot - s->slot - 1;
		publish_trigger(s, (struct trigger_event){rise_after, rise_after,
			s->slot + 2, s->epoch + (s->slot + 1) * PERIOD_NS, 10, SYNC_TRIGGER_GAP});
	}
	s->slot = next_slot;
	s->next = s->epoch + s->slot * PERIOD_NS;
	hrtimer_set_expires(timer, ns_to_ktime(s->next));
	return HRTIMER_RESTART;
}

static void reset(struct camss_sync *s){memset(s,0,sizeof(*s));s->running=true;
s->epoch=s->next=s->timer.expires=1000000000ULL;
asserts=releases=last_assert=last_release=0;gpio_error=fail_release=irq_held=0;
gpio_cost=high_gpio_cost=6000;pending_irq_delay=0;low_records=high_records=gap_records=0;}
int main(void){struct camss_sync s;reset(&s);
/* 20k complete pulses: all GPIO writes and pulse widths, no epoch drift. */
for(unsigned n=0;n<20000;n++){now=s.timer.expires;require(tick(&s.timer)==HRTIMER_RESTART);
require(last_assert==s.epoch+n*PERIOD_NS&&last_release-last_assert==PULSE_NS+gpio_cost);
require(s.slot==n+1&&!irq_held);}
require(asserts==20000&&releases==20000&&s.skipped==0&&low_records==20000&&high_records==20000);
/* Async association errors never become a new cadence epoch. */
s.error=11;now=s.timer.expires;require(tick(&s.timer)==HRTIMER_RESTART);
require(last_assert==s.epoch+20000*PERIOD_NS);
/* Early invocation has no GPIO side effect. */
reset(&s);now=s.next-1;require(tick(&s.timer)==HRTIMER_RESTART&&asserts==0&&s.next==s.epoch&&!irq_held);
/* Recorded 238603ns admission delay is safe under full-frame margin. */
reset(&s);now=s.next+238603;require(tick(&s.timer)==HRTIMER_RESTART&&asserts==1&&s.skipped==0);
require(last_release-last_assert==PULSE_NS+gpio_cost);
/* The release cannot be postponed by a pending normal IRQ in the model. */
reset(&s);pending_irq_delay=700000;now=s.next;require(tick(&s.timer)==HRTIMER_RESTART);
require(last_release-last_assert==PULSE_NS+gpio_cost&&pending_irq_delay==700000);
/* At the maximum admitted delay, a following early edge rearms rather than skips. */
reset(&s);now=s.next+LATE_BUDGET_NS;require(tick(&s.timer)==HRTIMER_RESTART);
u64 prior_low=s.last_assert_after,prior_high=s.last_deassert_after;
now=s.next;require(tick(&s.timer)==HRTIMER_RESTART&&asserts==1&&s.skipped==0&&s.slot==1);
require(s.timer.expires>s.next);now=s.timer.expires;require(tick(&s.timer)==HRTIMER_RESTART&&asserts==2&&s.skipped==0);
require(last_assert-prior_low>=PERIOD_NS-LATE_BUDGET_NS);
require(last_release-prior_high>=PERIOD_NS-LATE_BUDGET_NS);
require(s.next==s.epoch+2*PERIOD_NS);
/* Repeat measured and boundary jitter. No shortened intervals or catch-up burst. */
reset(&s);const u64 jitter[]={238603,0,499000,1000,450000,0};
for(unsigned n=0;n<6000;n++){u64 old=asserts;prior_low=s.last_assert_after;prior_high=s.last_deassert_after;
now=s.next+jitter[n%6];for(unsigned retry=0;retry<3&&asserts==old;retry++){
require(tick(&s.timer)==HRTIMER_RESTART);if(asserts==old)now=s.timer.expires;}
require(asserts==old+1&&s.skipped==0&&s.slot==n+1);
if(n){require(last_assert-prior_low>=PERIOD_NS-LATE_BUDGET_NS);
require(last_release-prior_high>=PERIOD_NS-LATE_BUDGET_NS);}}
/* Truly late admission still fails closed before GPIO: retain epoch and gap evidence. */
reset(&s);now=s.next+700000;require(tick(&s.timer)==HRTIMER_RESTART);
require(asserts==0&&s.slot==1&&s.skipped==1&&gap_records==1);
now=s.next;require(tick(&s.timer)==HRTIMER_RESTART&&asserts==1&&s.pulse_id==2);
reset(&s);now=s.epoch+40*PERIOD_NS+1000;require(tick(&s.timer)==HRTIMER_RESTART);
require(asserts==0&&s.slot==41&&s.skipped==41);
/* Recorded 117.9-minute failure: 33.227us low + 2.755us release fits 150us. */
reset(&s);gpio_cost=33227;high_gpio_cost=2755;now=s.next;
require(tick(&s.timer)==HRTIMER_RESTART&&!s.trigger_error&&asserts==1&&releases==1);
require(s.last_deassert_after-last_assert==135982);
/* The recorded 150.412us failure now fits the independent 200us envelope. */
reset(&s);gpio_cost=44634;high_gpio_cost=5778;now=s.next;
require(tick(&s.timer)==HRTIMER_RESTART&&!s.trigger_error);
require(s.last_deassert_after-last_assert==150412);
/* New total 200us bound, including exact and one-nanosecond boundaries. */
reset(&s);gpio_cost=98000;high_gpio_cost=2000;now=s.next;
require(tick(&s.timer)==HRTIMER_RESTART&&!s.trigger_error);
require(s.last_deassert_after-last_assert==200000);
reset(&s);gpio_cost=98001;high_gpio_cost=2000;now=s.next;
require(tick(&s.timer)==HRTIMER_NORESTART&&s.trigger_error==SYNC_PULSE_WIDTH&&!irq_held);
reset(&s);gpio_cost=90000;high_gpio_cost=20000;now=s.next;
require(tick(&s.timer)==HRTIMER_NORESTART&&s.trigger_error==SYNC_PULSE_WIDTH&&!irq_held);
/* Release 25us passes; 25.001us remains fatal below total 200us. */
reset(&s);gpio_cost=6000;high_gpio_cost=PULSE_OVERRUN_NS;now=s.next;
require(tick(&s.timer)==HRTIMER_RESTART&&!s.trigger_error);
reset(&s);gpio_cost=6000;high_gpio_cost=PULSE_OVERRUN_NS+1;now=s.next;
require(tick(&s.timer)==HRTIMER_NORESTART&&s.trigger_error==SYNC_PULSE_WIDTH&&!irq_held);
/* Both GPIO failures still stop and invalidate timing. */
reset(&s);gpio_error=-5;now=s.next;require(tick(&s.timer)==HRTIMER_NORESTART&&s.trigger_error==SYNC_GPIO&&!irq_held);
reset(&s);fail_release=1;now=s.next;require(tick(&s.timer)==HRTIMER_NORESTART&&s.trigger_error==SYNC_GPIO&&!irq_held);
reset(&s);s.running=false;require(tick(&s.timer)==HRTIMER_NORESTART&&asserts==0&&!irq_held);
puts("passed: 26000 full pulses, real callback, fixed epoch, measured jitter, spacing rearm, strict gaps/GPIO/timing failure");}
