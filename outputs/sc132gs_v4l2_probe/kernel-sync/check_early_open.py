#!/usr/bin/env python3
"""Compile the actual graph helper with a fixture for incomplete entities."""
from pathlib import Path
import subprocess
import sys
root=Path(sys.argv[1])
source=(root/'source/camss.c').read_text()
start=source.index('struct media_entity *camss_find_sensor(')
end=source.index('\n}',start)+2
prefix='''#include <stddef.h>
#define MEDIA_PAD_FL_SINK 1
#define MEDIA_ENT_F_CAM_SENSOR 2
struct media_entity;
struct media_pad { int flags; struct media_entity *entity; struct media_pad *remote; };
struct media_entity { unsigned num_pads; struct media_pad *pads; int function; int subdev; };
static struct media_pad *media_pad_remote_pad_first(struct media_pad *p) { return p->remote; }
static int is_media_entity_v4l2_subdev(struct media_entity *e) { return e->subdev; }
'''
main='''
int main(void) {
    struct media_entity empty={0};
    struct media_entity uninitialized={.num_pads=2};
    struct media_entity sensor={.function=MEDIA_ENT_F_CAM_SENSOR,.subdev=1};
    struct media_pad sensor_pad={.entity=&sensor};
    struct media_pad sink={.flags=MEDIA_PAD_FL_SINK,.remote=&sensor_pad};
    struct media_entity receiver={.num_pads=1,.pads=&sink};
    if(camss_find_sensor(NULL) || camss_find_sensor(&empty) || camss_find_sensor(&uninitialized)) return 1;
    if(camss_find_sensor(&receiver)!=&sensor) return 2;
    sink.remote=NULL;
    if(camss_find_sensor(&receiver)) return 3;
    return 0;
}
'''
fixture=root/'early-open-fixture.c'
fixture.write_text(prefix+source[start:end]+main)
subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra',str(fixture),'-o',str(root/'early-open-check')],check=True)
subprocess.run([str(root/'early-open-check')],check=True)
print('passed: actual helper rejects NULL/missing pads/unlinked media and follows a valid sensor link')
