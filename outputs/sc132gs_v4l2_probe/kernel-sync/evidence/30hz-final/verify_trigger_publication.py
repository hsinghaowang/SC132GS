#!/usr/bin/env python3
"""Test actual publication/worker code, bounded queue and lock separation."""
import argparse, hashlib, json, subprocess
from pathlib import Path
def extract(s, signature):
    a=s.index(signature); b=s.index('{',a); depth=1
    for i in range(b+1,len(s)):
        depth += (s[i]=='{')-(s[i]=='}')
        if not depth:return s[a:i+1]
    raise ValueError(signature)
parser=argparse.ArgumentParser();parser.add_argument('source',type=Path);parser.add_argument('out',type=Path)
a=parser.parse_args();a.out.mkdir(parents=True,exist_ok=True);s=a.source.read_text()
publish=extract(s,'static void publish_trigger(');drain=extract(s,'static void drain_triggers(')
assert 's->lock' not in publish
prefix=r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint64_t u64;typedef uint32_t u32;
#define TRIGGER_EVENTS 256
#define PULSES 128
#define SYNC_OVERFLOW 5
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
struct work_struct{int dummy;};
struct trigger_event{u64 before,after,id,extra;u32 kind,code;};
struct camss_sync_trigger{u64 id,before,after;};
struct camss_sync{int lock,trigger_lock,worker_cpu;struct work_struct trigger_work;
struct trigger_event pending[TRIGGER_EVENTS];u32 pending_head,pending_count,trigger_error,error;
struct camss_sync_trigger pulses[PULSES];bool running;u64 slot;};
static int raw_held,assoc_held;static unsigned records,scheduled;
static void raw_lock(void){if(raw_held||assoc_held)abort();raw_held=1;}
static void raw_unlock(void){if(!raw_held)abort();raw_held=0;}
static void assoc_lock(void){if(raw_held||assoc_held)abort();assoc_held=1;}
static void assoc_unlock(void){if(!assoc_held)abort();assoc_held=0;}
#define raw_spin_lock_irqsave(l,f) ((void)(l),(f)=0,raw_lock())
#define raw_spin_unlock_irqrestore(l,f) ((void)(l),(void)(f),raw_unlock())
#define spin_lock_irqsave(l,f) ((void)(l),(f)=0,assoc_lock())
#define spin_unlock_irqrestore(l,f) ((void)(l),(void)(f),assoc_unlock())
static int system_wq;
static void queue_work_on(int cpu,int wq,struct work_struct *w){(void)w;(void)wq;if(raw_held||cpu!=0)abort();scheduled++;}
static void fail(struct camss_sync*s,u32 code){if(!assoc_held)abort();s->error=code;}
static void record(struct camss_sync*s,u32 k,u32 eye,u64 before,u64 id,u64 after,u64 extra,u32 seq,u32 code){
(void)s;(void)k;(void)eye;(void)extra;(void)seq;(void)code;
if(!assoc_held||raw_held||before>after||id!=records+1){abort();}
records++;}
static void require(bool ok){if(!ok)abort();}
'''
tests=r'''
int main(void){struct camss_sync s={0};s.running=true;s.slot=73;
for(unsigned i=1;i<=256;i++)publish_trigger(&s,(struct trigger_event){i*100,i*100+6,i,0,1,0});
require(s.pending_count==256&&records==0&&scheduled==256);
publish_trigger(&s,(struct trigger_event){25700,25706,257,0,1,0});
require(s.trigger_error==5&&s.pending_count==256&&s.running&&s.slot==73);
drain_triggers(&s.trigger_work);
require(records==256&&s.pending_count==0&&s.error==5&&s.running&&s.slot==73);
require(s.pulses[257%128].id==257&&s.pulses[257%128].before==25700);
for(unsigned i=258;i<=1000;i++){
/* Gap 257 was the rejected diagnostic event, retain order of later records. */
records=i-1;publish_trigger(&s,(struct trigger_event){i*100,i*100+6,i,0,9,0});
drain_triggers(&s.trigger_work);require(records==i&&s.pending_count==0);}
puts("passed: actual producer/worker, asynchronous records, queue capacity/overflow, lock separation, lifecycle independence");}
'''
f=a.out/'fixture.c';f.write_text(prefix+publish+'\n'+drain+'\n'+tests)
subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(f),'-o',str(a.out/'fixture')],check=True)
subprocess.run([str((a.out/'fixture').resolve())],check=True)
(a.out/'result.json').write_text(json.dumps({'passed':True,'source_sha256':hashlib.sha256(a.source.read_bytes()).hexdigest(),'publication_sha256':hashlib.sha256(publish.encode()).hexdigest(),'worker_sha256':hashlib.sha256(drain.encode()).hexdigest(),'queue_capacity':256},indent=2)+'\n')
