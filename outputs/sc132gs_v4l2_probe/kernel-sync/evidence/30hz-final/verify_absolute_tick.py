#!/usr/bin/env python3
"""Compile and exercise the exact timer callback, with mocked GPIO/clock only."""
import argparse, hashlib, json, re, subprocess
from pathlib import Path
def extract(s, signature):
    a=s.index(signature); b=s.index('{',a); depth=1
    for i in range(b+1,len(s)):
        depth += (s[i]=='{')-(s[i]=='}')
        if not depth:return s[a:i+1]
    raise ValueError(signature)
parser=argparse.ArgumentParser(); parser.add_argument('source',type=Path); parser.add_argument('out',type=Path)
a=parser.parse_args(); a.out.mkdir(parents=True,exist_ok=True)
s=a.source.read_text(); callback=extract(s,'static enum hrtimer_restart tick(')
helper=extract((a.source.parent/'camss-sync-match.h').read_text(),'static inline __u64 camss_sync_future_slot(')
assert 's->lock' not in callback and 's->error' not in callback
prefix=r'''
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
'''
tests=r'''
static void reset(struct camss_sync *s){memset(s,0,sizeof(*s));s->running=true;
s->epoch=s->next=s->timer.expires=1000000000ULL;asserts=last_assert=0;gpio_error=0;}
int main(void){struct camss_sync s;reset(&s);
for(unsigned n=0;n<40000;n++){now=s.timer.expires;require(tick(&s.timer)==HRTIMER_RESTART);
if(n%2==0)require(last_assert==s.epoch+(n/2)*PERIOD_NS);}
require(asserts==20000&&s.skipped==0);
/* Frame association errors cannot stop or rebase the producer. */
s.error=11;now=s.timer.expires;require(tick(&s.timer)==HRTIMER_RESTART);
require(last_assert==s.epoch+20000*PERIOD_NS);
/* Early callbacks neither drive GPIO nor change the deadline. */
reset(&s);now=s.next-1;require(tick(&s.timer)==HRTIMER_RESTART&&asserts==0&&s.next==s.epoch);
/* Overrun jumps to a future absolute slot without a catch-up pulse. */
reset(&s);now=s.epoch+40*PERIOD_NS+1000;require(tick(&s.timer)==HRTIMER_RESTART);
require(asserts==0&&s.slot==41&&s.skipped==41&&s.next==s.epoch+41*PERIOD_NS);
now=s.next;require(tick(&s.timer)==HRTIMER_RESTART&&s.pulse_id==42);
now=s.pulse_end+40*PERIOD_NS;require(tick(&s.timer)==HRTIMER_RESTART&&s.next>now);
/* Known 700us late edge is skipped before touching GPIO; epoch survives. */
reset(&s);now=s.next+700000;require(tick(&s.timer)==HRTIMER_RESTART);
require(asserts==0&&s.slot==1&&s.skipped==1&&s.next==s.epoch+PERIOD_NS);
now=s.next;require(tick(&s.timer)==HRTIMER_RESTART&&asserts==1&&s.pulse_id==2);
/* A late deassertion also skips the following slot to protect rising edges. */
reset(&s);now=s.next;require(tick(&s.timer)==HRTIMER_RESTART);
now=s.pulse_end+700000;require(tick(&s.timer)==HRTIMER_RESTART);
now=s.next;require(tick(&s.timer)==HRTIMER_RESTART&&asserts==1&&s.slot==2);
now=s.next;require(tick(&s.timer)==HRTIMER_RESTART&&asserts==2&&s.pulse_id==3);
/* GPIO failure and lifecycle stop restore idle and stop callbacks. */
reset(&s);gpio_error=-5;now=s.next;require(tick(&s.timer)==HRTIMER_NORESTART&&s.trigger_error==1);
reset(&s);s.running=false;require(tick(&s.timer)==HRTIMER_NORESTART);
puts("passed: 40000 callbacks, absolute cadence, early/late/overrun, asynchronous frame error, GPIO failure, stop");}
'''
configuration={}
for name in ('PERIOD_NS','PULSE_NS','LATE_BUDGET_NS'):
    value=re.search(r'^#define\s+'+name+r'\s+(\d+)ULL',s,re.M).group(1)
    configuration[name]=int(value)
    prefix=re.sub(r'#define\s+'+name+r'\s+\d+ULL','#define '+name+' '+value+'ULL',prefix)
f=a.out/'fixture.c';f.write_text(prefix+helper+'\n'+callback+'\n'+tests)
subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(f),'-o',str(a.out/'fixture')],check=True)
subprocess.run([str((a.out/'fixture').resolve())],check=True)
(a.out/'result.json').write_text(json.dumps({'passed':True,'source_sha256':hashlib.sha256(a.source.read_bytes()).hexdigest(),'callback_sha256':hashlib.sha256(callback.encode()).hexdigest(),'callbacks':40000,'configuration_ns':configuration},indent=2)+'\n')
