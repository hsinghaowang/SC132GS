#!/usr/bin/env python3
"""Exercise actual SOF/DMA association functions with deterministic registers."""
import argparse,hashlib,json,subprocess
from pathlib import Path
def extract(s,signature):
    a=s.index(signature);b=s.index('{',a);depth=1
    for i in range(b+1,len(s)):
        depth+=(s[i]=='{')-(s[i]=='}')
        if not depth:return s[a:i+1]
    raise ValueError(signature)
p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('out',type=Path);a=p.parse_args()
a.out.mkdir(parents=True,exist_ok=True);source=a.source.read_text()
arm=extract(source,'void camss_sync_stream_started(')
sof=extract(source,'void camss_sync_sof(');done=extract(source,'bool camss_sync_done(');fail=extract(source,'static void fail(')
prefix=r'''
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "camss-sync-match.h"
typedef uint64_t u64;typedef uint32_t u32;
#define PULSES 128
#define FRAMES 32
#define ACQUIRE_NS 1000000000ULL
#define READ_ONCE(x) (x)
#define spin_lock_irqsave(l,f) ((void)(l),(f)=0)
#define spin_unlock_irqrestore(l,f) ((void)(l),(void)(f))
#define raw_spin_lock(l) ((void)(l))
#define raw_spin_unlock(l) ((void)(l))
enum sync_error { SYNC_OK,SYNC_GPIO,SYNC_NO_TRIGGER,SYNC_AMBIGUOUS,SYNC_DUPLICATE,
SYNC_OVERFLOW,SYNC_NO_SOF,SYNC_HW_REGRESSION,SYNC_NOT_RUNNING,SYNC_STARVATION,
SYNC_TRIGGER_GAP,SYNC_PHASE,SYNC_HARDWARE_FRAME,SYNC_ACQUIRING };
struct camss_sync;struct camss{struct camss_sync *sync;};
struct csid_device{struct camss *camss;u64 current_sof,previous,eof;};
struct vfe_device{struct camss *camss;};
struct camss_video{struct camss *camss;};
struct camss_buffer{struct{u32 sequence;struct{u64 timestamp;}vb2_buf;}vb;};
struct vfe_line{struct camss_video video_out;struct vfe_device *vfe;struct{void *buf[2];}output;};
struct frame_event{u64 trigger,timestamp,sof,hw_sof;bool startup;};
struct sync_eye{struct vfe_line *line;struct csid_device *csid;u32 rdi,head,count,startup_end;
u64 bind_hw,bind_ns,last_hw,last_trigger,sof_count,done_count;bool qualified,armed,first_post_arm;u64 arm_hw;struct frame_event frames[FRAMES];};
struct camss_sync{int lock,trigger_lock;bool running;u32 error,trigger_error;u64 error_count,pulse_id,startup_dropped;
struct sync_eye eyes[2];struct camss_sync_trigger pulses[PULSES];};
static unsigned fsync_mode=2,sof_min_us=15684,sof_max_us=16705;
static u64 timestamp_offset_ns,clock_ns,counter;static unsigned assertions;
static u64 arch_timer_read_counter(void){return counter;}
static u32 arch_timer_get_cntfrq(void){return 19200000;}
static u64 ktime_get_ns(void){return clock_ns;}
static u64 div_u64(u64 a,u32 b){return a/b;}
static struct vfe_device *to_vfe(struct vfe_line *l){return l->vfe;}
static u64 read_stamp(struct csid_device *c,u32 rdi,u32 off){(void)rdi;
return off==0x90?c->current_sof:off==0x98?c->previous:c->eof;}
static void record(struct camss_sync*s,u32 k,u32 eye,u64 ns,u64 x,u64 y,u64 z,u32 seq,u32 code){
(void)s;(void)k;(void)eye;(void)ns;(void)x;(void)y;(void)z;(void)seq;(void)code;}
static void check(bool ok){if(!ok){fprintf(stderr,"check %u failed\n",assertions);abort();}assertions++;}
'''
tests=r'''
static struct camss_sync sync_state;static struct camss device={&sync_state};
static struct csid_device csid[2];static struct vfe_device vfe={&device};
static struct vfe_line line[2];static struct camss_buffer buffer;
static void reset(void){memset(&sync_state,0,sizeof(sync_state));sync_state.running=true;
fsync_mode=2;timestamp_offset_ns=0;sof_min_us=15684;sof_max_us=16705;counter=100000;buffer.vb.vb2_buf.timestamp=99;
for(unsigned i=0;i<2;i++){csid[i]=(struct csid_device){.camss=&device};
line[i]=(struct vfe_line){.video_out={&device},.vfe=&vfe,.output={.buf={&buffer,&buffer}}};
sync_state.eyes[i]=(struct sync_eye){.line=&line[i],.csid=&csid[i],.armed=true,.first_post_arm=true};}
for(unsigned i=1;i<=128;i++){u64 t=1000000000ULL+i*33333333ULL;
sync_state.pulses[i%128]=(struct camss_sync_trigger){i,t,t+6000};}
}
static void frame(unsigned eye,unsigned id){clock_ns=1000000000ULL+id*33333333ULL+16182000;
counter+=100;csid[eye].previous=csid[eye].current_sof;
csid[eye].current_sof=counter;csid[eye].eof=counter+50;
camss_sync_sof(&csid[eye],0,counter);}
static bool deliver(unsigned eye){return camss_sync_done(&line[eye],&buffer,clock_ns+1000000);}
int main(void){
/* Apply one common output offset, without changing raw trigger/SOF identity. */
reset();timestamp_offset_ns=344903;frame(0,1);frame(1,1);
check(deliver(0)&&buffer.vb.vb2_buf.timestamp==sync_state.pulses[1].after+344903);
check(deliver(1)&&buffer.vb.vb2_buf.timestamp==sync_state.pulses[1].after+344903);
check(sync_state.eyes[0].last_trigger==1&&sync_state.eyes[1].last_trigger==1);
reset();fsync_mode=1;timestamp_offset_ns=344903;frame(0,1);
check(deliver(0)&&buffer.vb.vb2_buf.timestamp==99);
reset();timestamp_offset_ns=344903;frame(0,1);sync_state.trigger_error=SYNC_OVERFLOW;
check(!deliver(0)&&buffer.vb.vb2_buf.timestamp==99);
/* Arm only the eye owning this video device; record current hardware epoch. */
reset();sync_state.eyes[0].armed=false;sync_state.eyes[1].armed=false;
camss_sync_stream_started(&line[1].video_out);
check(!sync_state.eyes[0].armed&&sync_state.eyes[1].armed);
check(sync_state.eyes[1].arm_hw==counter);
camss_sync_stream_started(&line[0].video_out);check(sync_state.eyes[0].armed);
reset();frame(1,1);frame(0,1);check(deliver(0)&&deliver(1));
check(buffer.vb.vb2_buf.timestamp==sync_state.pulses[1].after);
frame(0,2);frame(1,2);check(deliver(1)&&deliver(0));
/* One eye misses a frame: fail, never infer identity from DMA/local sequence. */
frame(0,7);check(sync_state.error==SYNC_TRIGGER_GAP&&!deliver(0));
reset();frame(0,1);frame(1,2);check(deliver(0)&&deliver(1)&&sync_state.error==0);
reset();frame(0,1);frame(0,1);check(sync_state.error==SYNC_DUPLICATE&&!deliver(0));
reset();frame(0,1);csid[0].current_sof+=100;csid[0].eof+=100;
check(!deliver(0)&&sync_state.error==SYNC_HARDWARE_FRAME);
reset();frame(0,1);line[0].output.buf[1]=NULL;
check(!deliver(0)&&sync_state.error==SYNC_STARVATION);
reset();check(!deliver(0)&&sync_state.error==SYNC_NO_SOF);
reset();frame(0,1);sync_state.running=false;check(!deliver(0));
reset();sof_min_us=1;sof_max_us=100;frame(0,1);check(sync_state.error==SYNC_NO_TRIGGER&&!deliver(0));
reset();sof_min_us=1;sof_max_us=70000;frame(0,3);check(sync_state.error==SYNC_AMBIGUOUS&&!deliver(0));
reset();for(unsigned id=1;id<=33;id++)frame(0,id);
check(sync_state.error==SYNC_OVERFLOW&&sync_state.eyes[0].count==32&&!deliver(0));
reset();frame(0,1);sync_state.trigger_error=SYNC_OVERFLOW;
check(!deliver(0)&&buffer.vb.vb2_buf.timestamp==99);
reset();frame(0,1);check(deliver(0)&&sync_state.error==0);
reset();sync_state.eyes[0].bind_hw=1000000;frame(0,1);
check(sync_state.eyes[0].count==0&&sync_state.eyes[0].sof_count==0&&sync_state.error==0);
/* Even an in-window initial frame is untrusted until after STREAMON. */
reset();sync_state.eyes[0].bind_ns=1000000000;sync_state.eyes[0].armed=false;
frame(0,1);check(!deliver(0)&&sync_state.error==0&&sync_state.eyes[0].last_trigger==0);
sync_state.eyes[0].armed=true;sync_state.eyes[0].first_post_arm=false;
frame(0,2);check(!deliver(0)&&sync_state.error==0&&sync_state.eyes[0].last_trigger==0);
frame(0,3);check(deliver(0)&&sync_state.eyes[0].qualified&&sync_state.startup_dropped==2);
/* Unknown startup frame is ERROR with no assigned timestamp, then acquire. */
reset();sync_state.eyes[0].bind_ns=1000000000;
sof_min_us=17000;sof_max_us=18000;frame(0,1);
check(!deliver(0)&&sync_state.error==0&&sync_state.startup_dropped==1&&buffer.vb.vb2_buf.timestamp==99);
sof_min_us=15684;sof_max_us=16705;frame(0,2);
check(deliver(0)&&sync_state.eyes[0].qualified&&sync_state.error==0);
/* A missing association after locking is fatal even inside acquisition time. */
sof_min_us=17000;sof_max_us=18000;frame(0,3);check(!deliver(0)&&sync_state.error==SYNC_NO_TRIGGER);
/* An expired untrusted initial frame is fatal even inside the window. */
reset();sync_state.eyes[0].armed=false;frame(0,1);
check(!deliver(0)&&sync_state.error==SYNC_NO_TRIGGER&&buffer.vb.vb2_buf.timestamp==99);
/* Acquisition is bounded, not an indefinite discard policy. */
reset();sync_state.eyes[0].bind_ns=1;sof_min_us=17000;sof_max_us=18000;frame(0,1);
check(!deliver(0)&&sync_state.error==SYNC_NO_TRIGGER);
printf("passed: %u checks, actual SOF/DMA, reverse startup, single-eye loss, phase, duplicate, merged DMA, starvation, stop, ambiguity, overflow, restart\n",assertions);
}
'''
f=a.out/'fixture.c';f.write_text(prefix+fail+'\n'+arm+'\n'+sof+'\n'+done+'\n'+tests)
subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I'+str(a.source.parent),str(f),'-o',str(a.out/'fixture')],check=True)
subprocess.run([str((a.out/'fixture').resolve())],check=True)
(a.out/'result.json').write_text(json.dumps({'passed':True,'scope':'actual SOF/DMA functions with mocked hardware; board negative starvation separately measured',
'source_sha256':hashlib.sha256(a.source.read_bytes()).hexdigest(),'sof_sha256':hashlib.sha256(sof.encode()).hexdigest(),'done_sha256':hashlib.sha256(done.encode()).hexdigest()},indent=2)+'\n')
