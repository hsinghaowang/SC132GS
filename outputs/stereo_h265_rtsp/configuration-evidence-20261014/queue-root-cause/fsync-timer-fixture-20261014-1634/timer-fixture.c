#define PERIOD_NS 16666667ULL
#define PULSE_NS 100000ULL
#define PULSES 128

#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint64_t u64;
typedef uint64_t __u64;
typedef uint32_t u32;
enum hrtimer_restart { HRTIMER_NORESTART, HRTIMER_RESTART };
struct hrtimer { u64 expires; };
struct gpio_desc { int unused; };
struct camss_sync_trigger { u64 id, before, after; };
struct camss_sync {
    struct gpio_desc *gpio[2];
    struct hrtimer timer;
    int lock;
    bool running, asserted;
    u64 next, pulse_end, pulse_id, skipped;
    u32 error;
    struct camss_sync_trigger pulses[PULSES];
};
#define container_of(p, t, member) ((t *)((char *)(p) - offsetof(t, member)))
#define spin_lock_irqsave(lock, flags) ((void)(lock), (flags = 0))
#define spin_unlock_irqrestore(lock, flags) ((void)(lock), (void)(flags))
#define SYNC_GPIO 1
struct edge { u64 ns; unsigned level; };
static struct edge edges[20000];
static unsigned edge_count, idle_calls, assertion_records, deassertion_records;
static u64 now_ns;
static int fail_array;
static unsigned early_callbacks;
static u64 shortest_assert = UINT64_MAX, shortest_deassert = UINT64_MAX;
static u64 shortest_pulse = UINT64_MAX;
static u64 ktime_get_ns(void) { return now_ns; }
static u64 ns_to_ktime(u64 ns) { return ns; }
static void hrtimer_set_expires(struct hrtimer *t, u64 ns) { t->expires = ns; }
static int gpiod_set_array_value(unsigned n, struct gpio_desc **gpio,
                                 void *info, unsigned long *values) {
    (void)n; (void)gpio; (void)info;
    if (fail_array) { now_ns += 6000; return -5; }
    if (edge_count >= sizeof(edges)/sizeof(edges[0])) abort();
    edges[edge_count++] = (struct edge){ now_ns + 3000, (unsigned)*values };
    now_ns += 6000;
    return 0;
}
static void gpiod_set_value(struct gpio_desc *gpio, int value) {
    (void)gpio;
    if (value != 1) abort();
    ++idle_calls;
}
static void record(struct camss_sync *s, u32 kind, u32 eye, u64 ns,
                   u64 a, u64 b, u64 c, u32 sequence, u32 code) {
    (void)s; (void)eye; (void)a; (void)c; (void)sequence; (void)code;
    if (ns > b) abort();
    if (kind == 1) ++assertion_records;
    if (kind == 9) ++deassertion_records;
}

static inline __u64 camss_sync_next_assertion(__u64 deasserted_ns,
		__u64 period_ns, __u64 pulse_ns)
{
	return deasserted_ns + period_ns - pulse_ns;
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

static void require(bool ok, const char *what) {
    if (!ok) { fprintf(stderr, "failed: %s\n", what); exit(1); }
}
static void reset(struct camss_sync *s) {
    memset(s, 0, sizeof(*s));
    edge_count = idle_calls = assertion_records = deassertion_records = 0;
    now_ns = 0; fail_array = 0;
    s->running = true;
    s->next = s->timer.expires = 1000000000ULL;
}
static void check_edges(void) {
    u64 last[2] = {0,0};
    for (unsigned i = 0; i < edge_count; ++i) {
        unsigned polarity = edges[i].level == 3;
        require(edges[i].level == (i % 2 ? 3u : 0u), "GPIO transitions alternate");
        if (last[polarity]) {
            u64 interval = edges[i].ns - last[polarity];
            require(interval >= PERIOD_NS, "catch-up compressed like-polarity interval");
            u64 *shortest = polarity ? &shortest_deassert : &shortest_assert;
            if (interval < *shortest) *shortest = interval;
        }
        if (polarity) {
            u64 width = edges[i].ns - edges[i-1].ns;
            require(width >= PULSE_NS, "pulse shorter than configured duration");
            if (width < shortest_pulse) shortest_pulse = width;
        }
        last[polarity] = edges[i].ns;
    }
    require(assertion_records == (edge_count+1)/2, "assertion record count");
    require(deassertion_records == edge_count/2, "deassertion record count");
}
static void simulate(unsigned scenario) {
    struct camss_sync s; reset(&s);
    for (unsigned i = 0; i < 5000; ++i) {
        u64 due = s.timer.expires;
        u64 delay = 0;
        bool early = scenario == 3 && i % 79 == 0;
        if (scenario == 1) {
            if (i % 17 == 0) delay = 700000; /* observed scale of compression */
            else if (i % 29 == 0) delay = 1000000;
        } else if (scenario == 2 && i % 101 == 0) delay = 40000000;
        now_ns = early ? due - 50000 : due + delay;
        require(now_ns >= (edge_count ? edges[edge_count-1].ns : 0), "virtual monotonic time");
        unsigned old_edges = edge_count;
        require(tick(&s.timer) == HRTIMER_RESTART, "running timer unexpectedly stopped");
        if (early) {
            require(old_edges == edge_count, "early callback wrote GPIO");
            require(s.timer.expires == due, "early callback changed deadline");
            ++early_callbacks;
        }
        require(!s.error && s.running, "unexpected simulation error");
        require(s.timer.expires > now_ns, "timer scheduled into the past");
    }
    require(edge_count > 4000, "timer made insufficient progress");
    if (scenario == 2) require(s.skipped > 0, "missed slots were not accounted");
    check_edges();
}
static void errors_and_stop(void) {
    struct camss_sync s;
    reset(&s); fail_array = 1; now_ns = s.timer.expires;
    require(tick(&s.timer) == HRTIMER_NORESTART, "failed assertion kept timer running");
    require(s.error == SYNC_GPIO && !s.running && !s.pulse_id, "failed assertion state");
    require(idle_calls == 2 && !edge_count, "failed assertion did not restore idle");
    reset(&s); now_ns = s.timer.expires;
    require(tick(&s.timer) == HRTIMER_RESTART, "prepare deassertion fixture");
    now_ns = s.timer.expires; fail_array = 1;
    require(tick(&s.timer) == HRTIMER_RESTART && s.error == SYNC_GPIO,
            "failed deassertion did not record error");
    now_ns = s.timer.expires;
    require(tick(&s.timer) == HRTIMER_NORESTART && !s.running && s.pulse_id == 1,
            "failed deassertion emitted another pulse");
    require(idle_calls == 2, "failed deassertion did not restore idle");
    reset(&s); s.running = false; now_ns = s.timer.expires;
    require(tick(&s.timer) == HRTIMER_NORESTART && idle_calls == 2 && !edge_count,
            "stopped session restarted output");
    reset(&s); s.error = 10; now_ns = s.timer.expires;
    require(tick(&s.timer) == HRTIMER_NORESTART && !s.running && !edge_count,
            "failed session restarted output");
}
int main(void) {
    for (unsigned scenario = 0; scenario < 4; ++scenario) simulate(scenario);
    errors_and_stop();
    printf("{\"passed\":true,\"scenarios\":4,\"callback_invocations\":20000,"
           "\"early_callbacks\":%u,\"minimum_assert_interval_ns\":%llu,"
           "\"minimum_deassert_interval_ns\":%llu,\"minimum_pulse_ns\":%llu}\\n",
           early_callbacks, (unsigned long long)shortest_assert,
           (unsigned long long)shortest_deassert, (unsigned long long)shortest_pulse);
    return 0;
}
