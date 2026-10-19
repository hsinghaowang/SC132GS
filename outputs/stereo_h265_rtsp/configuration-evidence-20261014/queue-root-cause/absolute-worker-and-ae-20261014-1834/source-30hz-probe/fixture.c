
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint64_t u64; typedef uint64_t __u64; typedef uint32_t u32;
#define PERIOD_NS 33333333ULL
#define PULSE_NS 100000ULL
#define LATE_BUDGET_NS 100000ULL
#define SYNC_TRIGGER_GAP 10
#define SYNC_GPIO 1
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
enum hrtimer_restart { HRTIMER_NORESTART,HRTIMER_RESTART };
struct hrtimer {u64 expires;}; struct gpio_desc {int x;};
struct trigger_event {u64 before,after,id,extra;u32 kind,code;};
struct camss_sync {struct hrtimer timer;struct gpio_desc *gpio[2];bool running,asserted;
u64 epoch,slot,next,pulse_end,pulse_id,skipped,last_assert_after,last_deassert_after;u32 trigger_error,error;};
static u64 now,asserts,last_assert;static int gpio_error;
static u64 ktime_get_ns(void){return now;}
static u64 ns_to_ktime(u64 n){return n;}
static void hrtimer_set_expires(struct hrtimer *t,u64 n){t->expires=n;}
static void gpiod_set_value(struct gpio_desc *g,int v){(void)g;(void)v;}
static int gpiod_set_array_value(int n,struct gpio_desc **g,void *i,unsigned long *v){
(void)n;(void)g;(void)i;if(!*v){asserts++;last_assert=now;}now+=6000;return gpio_error;}
static void publish_trigger(struct camss_sync *s,struct trigger_event e){
(void)s;if(e.after<e.before)abort();}
static void require(bool b){if(!b)abort();}

static inline __u64 camss_sync_future_slot(__u64 epoch, __u64 now,
		__u64 period_ns)
{
	return now < epoch ? 0 : (now - epoch) / period_ns + 1;
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

int main(void) {
    struct camss_sync s = {0};
    s.running = true;
    s.epoch = s.next = s.timer.expires = 1000000000ULL;
    gpio_error = 0;
    now = s.next + 700000;
    enum hrtimer_restart status = tick(&s.timer);
    require(s.epoch == 1000000000ULL);
    if (!asserts) {
        printf("{\"passed\":true,\"first_assertion_skipped\":true,"
               "\"next_deadline_ns\":%llu,\"callback_status\":%d}\n",
               (unsigned long long)s.next, status);
        return 0;
    }
    u64 first = last_assert;
    now = s.timer.expires;
    require(tick(&s.timer) == HRTIMER_RESTART);
    now = s.timer.expires;
    require(tick(&s.timer) == HRTIMER_RESTART);
    require(asserts == 2 && last_assert > first);
    u64 interval = last_assert - first;
    /* Previous board evidence: 15,984,272 ns preceded both-eye trigger gap.
     * Reject recreating an interval at least that short. No claim is made
     * about the full range of sensor-acceptable intervals. */
    printf("{\"passed\":%s,\"first_assertion_skipped\":false,"
           "\"late_by_ns\":700000,\"assertion_interval_ns\":%llu,"
           "\"observed_bad_interval_ns\":15984272}\n",
           interval > 15984272 ? "true" : "false", (unsigned long long)interval);
    return 0;
}
