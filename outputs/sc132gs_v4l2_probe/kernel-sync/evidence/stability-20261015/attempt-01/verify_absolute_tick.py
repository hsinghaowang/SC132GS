#!/usr/bin/env python3
"""Exercise the exact atomic-pulse callback with virtual time and GPIO only."""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path


def extract(source, signature):
    start = source.index(signature)
    brace = source.index('{', start)
    depth = 1
    for index in range(brace + 1, len(source)):
        depth += (source[index] == '{') - (source[index] == '}')
        if not depth:
            return source[start:index + 1]
    raise ValueError(signature)


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('source', type=Path)
parser.add_argument('out', type=Path)
args = parser.parse_args()
args.out.mkdir(parents=True, exist_ok=True)
source = args.source.read_text()
callback = extract(source, 'static enum hrtimer_restart tick(')
helpers = (args.source.parent / 'camss-sync-match.h').read_text()
helpers = '\n'.join(extract(helpers, 'static inline __u64 ' + name + '(')
                    for name in ['camss_sync_future_slot', 'camss_sync_earliest_edge'])
assert 's->lock' not in callback and 's->error' not in callback
assert 'HRTIMER_MODE_ABS_PINNED_HARD' in source
prefix = r'''
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
static u64 now,asserts,releases,last_assert,last_release,gpio_cost,pending_irq_delay;
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
now+=gpio_cost;return (*values&&fail_release)?-5:gpio_error;}
static void publish_trigger(struct camss_sync *sync,struct trigger_event event){
(void)sync;require(!irq_held&&event.after>=event.before);
if(event.kind==1){low_records++;}
if(event.kind==9){high_records++;}
if(event.kind==10){gap_records++;}}
'''
tests = r'''
static void reset(struct camss_sync *s){memset(s,0,sizeof(*s));s->running=true;
s->epoch=s->next=s->timer.expires=1000000000ULL;
asserts=releases=last_assert=last_release=0;gpio_error=fail_release=irq_held=0;
gpio_cost=6000;pending_irq_delay=0;low_records=high_records=gap_records=0;}
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
/* Both GPIO failures and excessive command duration stop, never publish valid timing. */
reset(&s);gpio_error=-5;now=s.next;require(tick(&s.timer)==HRTIMER_NORESTART&&s.trigger_error==SYNC_GPIO&&!irq_held);
reset(&s);fail_release=1;now=s.next;require(tick(&s.timer)==HRTIMER_NORESTART&&s.trigger_error==SYNC_GPIO&&!irq_held);
reset(&s);gpio_cost=PULSE_OVERRUN_NS+1;now=s.next;require(tick(&s.timer)==HRTIMER_NORESTART&&s.trigger_error==SYNC_PULSE_WIDTH&&!irq_held);
reset(&s);s.running=false;require(tick(&s.timer)==HRTIMER_NORESTART&&asserts==0&&!irq_held);
puts("passed: 26000 full pulses, real callback, fixed epoch, measured jitter, spacing rearm, strict gaps/GPIO/timing failure");}
'''
configuration = {}
for name in ['PERIOD_NS', 'PULSE_NS', 'LATE_BUDGET_NS', 'PULSE_OVERRUN_NS']:
    value = re.search(r'^#define\s+' + name + r'\s+(\d+)ULL', source, re.M).group(1)
    configuration[name] = int(value)
    prefix = re.sub(r'#define\s+' + name + r'\s+\d+ULL', '#define ' + name + ' ' + value + 'ULL', prefix)
fixture = args.out / 'fixture.c'
fixture.write_text(prefix + helpers + '\n' + callback + '\n' + tests)
subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', str(fixture), '-o', str(args.out / 'fixture')], check=True)
subprocess.run([str((args.out / 'fixture').resolve())], check=True)
(args.out / 'result.json').write_text(json.dumps({
    'passed': True, 'source_sha256': hashlib.sha256(args.source.read_bytes()).hexdigest(),
    'callback_sha256': hashlib.sha256(callback.encode()).hexdigest(), 'full_pulses': 26000,
    'configuration_ns': configuration,
    'scope': 'actual callback with virtual time/GPIO/IRQ; no electrical or platform latency proof'}, indent=2) + '\n')
