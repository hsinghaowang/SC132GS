#!/usr/bin/env python3
"""Compile the real ISR against deterministic register/IRQ fixtures.

The async fixture inserts WM0 completion between top-status and bus-status
reads. It proves the old ISR consumes completion without notifying VB2 and
that the backport dispatches it once. This is source-level proof, not hardware.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def function(source, signature):
    begin = source.index(signature)
    opening = source.index('{', begin)
    depth = 1
    for end in range(opening + 1, len(source)):
        depth += (source[end] == '{') - (source[end] == '}')
        if depth == 0:
            return source[begin:end + 1]
    raise RuntimeError('Unclosed ISR function')


def macros(source):
    result = []
    continuation = False
    for line in source.splitlines():
        if continuation or re.match(r'\s*#define\s', line):
            result.append(line)
            continuation = line.endswith('\\')
    return '\n'.join(result)


PREFIX = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint32_t u32;
typedef uint8_t u8;
typedef int irqreturn_t;
#define IRQ_HANDLED 1
#define BIT(n) (1u << (n))
#define MSM_VFE_IMAGE_MASTERS_NUM 7
#define MSM_VFE_COMPOSITE_IRQ_NUM 4
#define VFE_LINE_NUM_MAX 4
#define VFE_LINE_RDI0 0
struct vfe_device;
struct resource { int line_num; };
struct callbacks {
    void (*reset_ack)(struct vfe_device *);
    void (*reg_update)(struct vfe_device *, int);
    void (*sof)(struct vfe_device *, int);
    void (*comp_done)(struct vfe_device *, int);
    void (*wm_done)(struct vfe_device *, u8);
};
struct vfe_device {
    unsigned char *base;
    struct resource *res;
    struct callbacks isr_ops;
};
static uint32_t registers[0x3000/4];
static unsigned completions[MSM_VFE_IMAGE_MASTERS_NUM];
static int async_arrival;
static void noop(struct vfe_device *vfe) { (void)vfe; }
static void noop_index(struct vfe_device *vfe, int index) { (void)vfe; (void)index; }
static void complete_wm(struct vfe_device *vfe, u8 wm) { (void)vfe; ++completions[wm]; }
static void wmb(void) {}
'''

MMIO = r'''
static uint32_t readl_relaxed(const unsigned char *address) {
    const size_t offset = address - (const unsigned char *)registers;
    if (async_arrival && offset == VFE_BUS_IRQ_STATUS(1)) {
        registers[VFE_BUS_IRQ_STATUS(1)/4] |= STATUS1_WM_CLIENT_BUF_DONE(0);
        registers[VFE_IRQ_STATUS_0/4] |= BIT(9);
        async_arrival = 0;
    }
    return registers[offset/4];
}
static void writel_relaxed(uint32_t value, unsigned char *address) {
    const size_t offset = address - (unsigned char *)registers;
    registers[offset/4] = value;
    if (offset == VFE_IRQ_CLEAR_0) registers[VFE_IRQ_STATUS_0/4] &= ~value;
    if (offset == VFE_IRQ_CLEAR_1) registers[VFE_IRQ_STATUS_1/4] &= ~value;
    for (unsigned i=0; i<VFE_LINE_NUM_MAX; ++i)
        if (offset == VFE_BUS_IRQ_CLEAR(i)) registers[VFE_BUS_IRQ_STATUS(i)/4] &= ~value;
}
'''

MAIN = r'''
static void require(int condition, const char *message) {
    if (!condition) { fprintf(stderr, "%s\n", message); exit(1); }
}
int main(void) {
    struct resource resource = {3};
    struct vfe_device device = {(unsigned char *)registers, &resource,
        {noop, noop_index, noop_index, noop_index, complete_wm}};
    unsigned cases=0;
    for (unsigned bus=0; bus<128; ++bus) {
        for (unsigned top=0; top<2; ++top) {
            memset(registers,0,sizeof(registers)); memset(completions,0,sizeof(completions));
            registers[VFE_IRQ_STATUS_0/4] = top ? BIT(9) : 0;
            registers[VFE_BUS_IRQ_STATUS(1)/4] = bus;
            vfe_isr(240,&device);
            for (unsigned wm=0; wm<MSM_VFE_IMAGE_MASTERS_NUM; ++wm) {
                const unsigned expected = ((bus>>wm)&1) && (EXPECT_FIXED || top);
                require(completions[wm]==expected, "completion dispatch matrix failed");
            }
            require(registers[VFE_BUS_IRQ_STATUS(1)/4]==0, "bus status was not consumed");
            ++cases;
        }
    }
    memset(registers,0,sizeof(registers)); memset(completions,0,sizeof(completions));
    registers[VFE_IRQ_STATUS_0/4]=STATUS_1_RDI_SOF(0);
    async_arrival=1;
    vfe_isr(240,&device);
    require(registers[VFE_BUS_IRQ_STATUS(1)/4]==0, "async completion was not consumed");
    require(completions[0]==EXPECT_FIXED, "async completion recovery failed");
    for(unsigned wm=1;wm<MSM_VFE_IMAGE_MASTERS_NUM;++wm)
        require(completions[wm]==0, "another write master was incorrectly completed");
    const unsigned async_completed=completions[0];
    memset(registers,0,sizeof(registers)); memset(completions,0,sizeof(completions));
    registers[VFE_BUS_IRQ_STATUS(1)/4]=STATUS1_EARLY_DONE;
    vfe_isr(240,&device);
    for(unsigned wm=0;wm<MSM_VFE_IMAGE_MASTERS_NUM;++wm)
        require(completions[wm]==0, "early-done was incorrectly dispatched as a buffer");
    printf("{\"dispatch_cases\":%u,\"async_completed\":%u,\"fixed\":%s}\n",
           cases,async_completed,EXPECT_FIXED ? "true" : "false");
    return 0;
}
'''


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--fixed', action='store_true')
    args = parser.parse_args()
    source = args.source.read_text()
    isr = function(source, 'static irqreturn_t vfe_isr(')
    if ('if (status0 & BIT(9))' in isr) == args.fixed:
        raise SystemExit('Source gate does not match requested original/fixed case')
    args.output.mkdir(parents=True, exist_ok=False)
    fixture = args.output / 'isr-fixture.c'
    fixture.write_text(PREFIX + macros(source) + '\n' + MMIO + '\n' + isr + '\n' + MAIN)
    executable = args.output / 'isr-fixture'
    subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Wpedantic','-Wno-unused-parameter',
                    '-DEXPECT_FIXED='+str(int(args.fixed)), str(fixture), '-o',str(executable)], check=True)
    result = subprocess.run([str(executable)], text=True, capture_output=True, check=True)
    report = json.loads(result.stdout)
    report.update(source_sha256=hashlib.sha256(args.source.read_bytes()).hexdigest(),
                  scope='actual ISR with deterministic MMIO fixtures; not physical hardware')
    (args.output/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))
