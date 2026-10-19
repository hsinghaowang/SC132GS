
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
static void fail(struct camss_sync *s, enum sync_error error)
{
	if (fsync_mode == 2) s->error_count++;
	if (fsync_mode == 2 && !s->error) {
		s->error = error;
		record(s, 4, 2, ktime_get_ns(), 0, 0, 0, 0, error);
	}
}
void camss_sync_stream_started(struct camss_video *video)
{
	struct camss_sync *s = video->camss->sync;
	unsigned long flags;
	u32 i;
	if (!s) return;
	spin_lock_irqsave(&s->lock, flags);
	for (i = 0; i < 2; i++) {
		struct sync_eye *e = &s->eyes[i];
		if (e->line && &e->line->video_out == video) {
			e->arm_hw = arch_timer_read_counter();
			e->armed = true;
			record(s, 14, i, ktime_get_ns(), e->arm_hw, 0, 0, 0, 0);
		}
	}
	spin_unlock_irqrestore(&s->lock, flags);
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
	bool acquiring = false;
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
	if (fsync_mode == 2 && !e->last_trigger) {
		bool initial = !e->armed || hw_sof < e->arm_hw;
		if (!initial && !e->first_post_arm) {
			e->first_post_arm = true;
			initial = true;
		}
		acquiring = (initial || matches == 0) &&
			irq_ns >= e->bind_ns && irq_ns - e->bind_ns < ACQUIRE_NS;
		if (initial && !acquiring) fail(s, SYNC_NO_TRIGGER);
	}
	/* Ambiguity, hardware regressions and overflow remain fatal even while
	 * acquiring.  Untrusted startup frames never receive a trigger identity. */
	if (matches > 1) fail(s, SYNC_AMBIGUOUS);
	else if (matches != 1 && !acquiring) fail(s, SYNC_NO_TRIGGER);
	if (!acquiring && matches == 1) {
		if (found.id <= e->last_trigger) fail(s, SYNC_DUPLICATE);
		if (e->last_trigger && found.id != e->last_trigger + 1)
			fail(s, SYNC_TRIGGER_GAP);
		e->last_trigger = found.id;
	}
	record(s, 2, eye, now, acquiring ? 0 : found.id, hw_sof, s->pulse_id, e->sof_count,
		acquiring ? SYNC_ACQUIRING : matches != 1);
	if (e->count == FRAMES) { fail(s, SYNC_OVERFLOW); goto out; }
	e->frames[(e->head + e->count) % FRAMES] = (struct frame_event){
		.trigger = !acquiring && matches == 1 ? found.id : 0,
		.timestamp = acquiring ? 0 : found.after,
		.sof = now, .hw_sof = hw_sof, .startup = acquiring};
	e->count++;
out:
	spin_unlock_irqrestore(&s->lock, flags);
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
	if (!e->count) {
		if (fsync_mode == 2 && !e->last_trigger && done_ns >= e->bind_ns &&
		    done_ns - e->bind_ns < ACQUIRE_NS)
			frame.startup = true;
		else
			fail(s, SYNC_NO_SOF);
	}
	else {
		frame = e->frames[e->head];
		e->head = (e->head + 1) % FRAMES; e->count--;
	}
	if (!line->output.buf[1]) fail(s, SYNC_STARVATION);
	if (!s->running || (!frame.trigger && !frame.startup)) fail(s, SYNC_NO_TRIGGER);
	if (frame.hw_sof) {
		u64 current_sof = read_stamp(e->csid, e->rdi, 0x90);
		u64 previous = read_stamp(e->csid, e->rdi, 0x98);
		u64 eof = read_stamp(e->csid, e->rdi, 0xa0);
		bool hw_valid = camss_sync_hardware_frame(frame.hw_sof, current_sof, previous, eof);
		if (!hw_valid)
			fail(s, SYNC_HARDWARE_FRAME);
		record(s, 7, eye, done_ns, current_sof, previous, eof, buffer->vb.sequence, hw_valid ? 0 : SYNC_HARDWARE_FRAME);
	}
	if (frame.startup) {
		s->startup_dropped++;
		e->startup_end = buffer->vb.sequence + 1;
	}
	record(s, 3, eye, done_ns, frame.trigger, frame.hw_sof, frame.sof,
		buffer->vb.sequence, s->error ? s->error : frame.startup ? SYNC_ACQUIRING : 0);
out:
	if (fsync_mode == 2) {
		valid = !s->error && !READ_ONCE(s->trigger_error) && frame.trigger;
		if (valid) {
			/* Identity and raw trigger timestamps remain unchanged. */
			buffer->vb.vb2_buf.timestamp = frame.timestamp + timestamp_offset_ns;
			e->qualified = true;
		}
	}
	spin_unlock_irqrestore(&s->lock, flags);
	return valid;
}

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
