
/home/ubuntu/sc132gs-camera-tests/integer-fps-20261007/camss-inspection.ko:     file format elf64-littleaarch64


Disassembly of section .text:

0000000000023a00 <vfe_isr_wm_done>:
   23a00:	d503201f 	nop
   23a04:	d503201f 	nop
   23a08:	d503233f 	paciasp
   23a0c:	f800865e 	str	x30, [x18], #8
   23a10:	a9b97bfd 	stp	x29, x30, [sp, #-112]!
   23a14:	910003fd 	mov	x29, sp
   23a18:	a90153f3 	stp	x19, x20, [sp, #16]
   23a1c:	aa0003f3 	mov	x19, x0
   23a20:	12001c34 	and	w20, w1, #0xff
   23a24:	a9025bf5 	stp	x21, x22, [sp, #32]
   23a28:	a90363f7 	stp	x23, x24, [sp, #48]
   23a2c:	aa1e03f7 	mov	x23, x30
   23a30:	a9046bf9 	stp	x25, x26, [sp, #64]
   23a34:	92401c3a 	and	x26, x1, #0xff
   23a38:	f1001f5f 	cmp	x26, #0x7
   23a3c:	54001962 	b.cs	23d68 <vfe_isr_wm_done+0x368>  // b.hs, b.nlast
   23a40:	8b340a74 	add	x20, x19, w20, uxtb #2
   23a44:	b980e295 	ldrsw	x21, [x20, #224]
   23a48:	f10016bf 	cmp	x21, #0x5
   23a4c:	54001822 	b.cs	23d50 <vfe_isr_wm_done+0x350>  // b.hs, b.nlast
   23a50:	94000000 	bl	0 <ktime_get>
			23a50: R_AARCH64_CALL26	ktime_get
   23a54:	91037279 	add	x25, x19, #0xdc
   23a58:	aa0003f8 	mov	x24, x0
   23a5c:	aa1903e0 	mov	x0, x25
   23a60:	94000000 	bl	0 <_raw_spin_lock_irqsave>
			23a60: R_AARCH64_CALL26	_raw_spin_lock_irqsave
   23a64:	aa0003f6 	mov	x22, x0
   23a68:	f1001f5f 	cmp	x26, #0x7
   23a6c:	54001662 	b.cs	23d38 <vfe_isr_wm_done+0x338>  // b.hs, b.nlast
   23a70:	b940e294 	ldr	w20, [x20, #224]
   23a74:	3100069f 	cmn	w20, #0x1
   23a78:	54000fa0 	b.eq	23c6c <vfe_isr_wm_done+0x26c>  // b.none
   23a7c:	a90573fb 	stp	x27, x28, [sp, #80]
   23a80:	f1001f5f 	cmp	x26, #0x7
   23a84:	540018a2 	b.cs	23d98 <vfe_isr_wm_done+0x398>  // b.hs, b.nlast
   23a88:	93407e94 	sxtw	x20, w20
   23a8c:	f100129f 	cmp	x20, #0x4
   23a90:	54001782 	b.cs	23d80 <vfe_isr_wm_done+0x380>  // b.hs, b.nlast
   23a94:	d2815d02 	mov	x2, #0xae8                 	// #2792
   23a98:	9b027e82 	mul	x2, x20, x2
   23a9c:	8b02027b 	add	x27, x19, x2
   23aa0:	912d4042 	add	x2, x2, #0xb50
   23aa4:	8b020260 	add	x0, x19, x2
   23aa8:	f945af7a 	ldr	x26, [x27, #2904]
   23aac:	b400117a 	cbz	x26, 23cd8 <vfe_isr_wm_done+0x2d8>
   23ab0:	f9000f58 	str	x24, [x26, #24]
   23ab4:	b94b9361 	ldr	w1, [x27, #2960]
   23ab8:	11000422 	add	w2, w1, #0x1
   23abc:	b90b9362 	str	w2, [x27, #2960]
   23ac0:	b9021b41 	str	w1, [x26, #536]
   23ac4:	f945b361 	ldr	x1, [x27, #2912]
   23ac8:	f905af61 	str	x1, [x27, #2904]
   23acc:	f100003f 	cmp	x1, #0x0
   23ad0:	9a9f07f8 	cset	x24, ne	// ne = any
   23ad4:	94000000 	bl	2b688 <vfe_buf_get_pending>
			23ad4: R_AARCH64_CALL26	vfe_buf_get_pending
   23ad8:	d2802ba1 	mov	x1, #0x15d                 	// #349
   23adc:	9b016281 	madd	x1, x20, x1, x24
   23ae0:	8b010e61 	add	x1, x19, x1, lsl #3
   23ae4:	f905ac20 	str	x0, [x1, #2904]
   23ae8:	b4000620 	cbz	x0, 23bac <vfe_isr_wm_done+0x1ac>
   23aec:	d2815d01 	mov	x1, #0xae8                 	// #2792
   23af0:	f9400a62 	ldr	x2, [x19, #16]
   23af4:	9b014e94 	madd	x20, x20, x1, x19
   23af8:	9b014eb5 	madd	x21, x21, x1, x19
   23afc:	52844281 	mov	w1, #0x2214                	// #8724
   23b00:	f941d41c 	ldr	x28, [x0, #936]
   23b04:	9127e2b5 	add	x21, x21, #0x9f8
   23b08:	396d4694 	ldrb	w20, [x20, #2897]
   23b0c:	b9401ab8 	ldr	w24, [x21, #24]
   23b10:	2a1c03e5 	mov	w5, w28
   23b14:	53185e94 	lsl	w20, w20, #8
   23b18:	0b01029b 	add	w27, w20, w1
   23b1c:	8b3b405b 	add	x27, x2, w27, uxtw
   23b20:	d503201f 	nop
   23b24:	b9000365 	str	w5, [x27]
   23b28:	d503201f 	nop
   23b2c:	52844b00 	mov	w0, #0x2258                	// #8792
   23b30:	b94006a1 	ldr	w1, [x21, #4]
   23b34:	0b000294 	add	w20, w20, w0
   23b38:	f9400a60 	ldr	x0, [x19, #16]
   23b3c:	1b017f18 	mul	w24, w24, w1
   23b40:	8b344014 	add	x20, x0, w20, uxtw
   23b44:	d503201f 	nop
   23b48:	b9000298 	str	w24, [x20]
   23b4c:	d503201f 	nop
   23b50:	aa1603e1 	mov	x1, x22
   23b54:	aa1903e0 	mov	x0, x25
   23b58:	94000000 	bl	0 <_raw_spin_unlock_irqrestore>
			23b58: R_AARCH64_CALL26	_raw_spin_unlock_irqrestore
   23b5c:	aa1a03e0 	mov	x0, x26
   23b60:	528000a1 	mov	w1, #0x5                   	// #5
   23b64:	94000000 	bl	0 <vb2_buffer_done>
			23b64: R_AARCH64_CALL26	vb2_buffer_done
   23b68:	a94153f3 	ldp	x19, x20, [sp, #16]
   23b6c:	a9425bf5 	ldp	x21, x22, [sp, #32]
   23b70:	a94363f7 	ldp	x23, x24, [sp, #48]
   23b74:	a9446bf9 	ldp	x25, x26, [sp, #64]
   23b78:	a94573fb 	ldp	x27, x28, [sp, #80]
   23b7c:	f85f8e5e 	ldr	x30, [x18, #-8]!
   23b80:	f84707fd 	ldr	x29, [sp], #112
   23b84:	d50323bf 	autiasp
   23b88:	d2800000 	mov	x0, #0x0                   	// #0
   23b8c:	d2800001 	mov	x1, #0x0                   	// #0
   23b90:	d2800002 	mov	x2, #0x0                   	// #0
   23b94:	d2800003 	mov	x3, #0x0                   	// #0
   23b98:	d2800004 	mov	x4, #0x0                   	// #0
   23b9c:	d2800005 	mov	x5, #0x0                   	// #0
   23ba0:	d2800010 	mov	x16, #0x0                   	// #0
   23ba4:	d2800011 	mov	x17, #0x0                   	// #0
   23ba8:	d65f03c0 	ret
   23bac:	d2815d00 	mov	x0, #0xae8                 	// #2792
   23bb0:	9b004e94 	madd	x20, x20, x0, x19
   23bb4:	b94b8680 	ldr	w0, [x20, #2948]
   23bb8:	51000400 	sub	w0, w0, #0x1
   23bbc:	b90b8680 	str	w0, [x20, #2948]
   23bc0:	17ffffe4 	b	23b50 <vfe_isr_wm_done+0x150>
   23bc4:	aa1703fe 	mov	x30, x23
   23bc8:	d50320ff 	xpaclri
   23bcc:	aa1403e2 	mov	x2, x20
   23bd0:	aa1e03e4 	mov	x4, x30
   23bd4:	2a1803e0 	mov	w0, w24
   23bd8:	90000003 	adrp	x3, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			23bd8: R_AARCH64_ADR_PREL_PG_HI21	.text+0x23bc4
   23bdc:	52800401 	mov	w1, #0x20                  	// #32
   23be0:	91000063 	add	x3, x3, #0x0
			23be0: R_AARCH64_ADD_ABS_LO12_NC	.text+0x23bc4
   23be4:	94000000 	bl	0 <log_post_write_mmio>
			23be4: R_AARCH64_CALL26	log_post_write_mmio
   23be8:	17ffffda 	b	23b50 <vfe_isr_wm_done+0x150>
   23bec:	aa1703fe 	mov	x30, x23
   23bf0:	d50320ff 	xpaclri
   23bf4:	aa1403e2 	mov	x2, x20
   23bf8:	aa1e03e4 	mov	x4, x30
   23bfc:	2a1803e0 	mov	w0, w24
   23c00:	90000003 	adrp	x3, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			23c00: R_AARCH64_ADR_PREL_PG_HI21	.text+0x23bec
   23c04:	52800401 	mov	w1, #0x20                  	// #32
   23c08:	91000063 	add	x3, x3, #0x0
			23c08: R_AARCH64_ADD_ABS_LO12_NC	.text+0x23bec
   23c0c:	94000000 	bl	0 <log_write_mmio>
			23c0c: R_AARCH64_CALL26	log_write_mmio
   23c10:	17ffffce 	b	23b48 <vfe_isr_wm_done+0x148>
   23c14:	aa1703fe 	mov	x30, x23
   23c18:	d50320ff 	xpaclri
   23c1c:	aa1b03e2 	mov	x2, x27
   23c20:	aa1e03e4 	mov	x4, x30
   23c24:	2a1c03e0 	mov	w0, w28
   23c28:	90000003 	adrp	x3, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			23c28: R_AARCH64_ADR_PREL_PG_HI21	.text+0x23c14
   23c2c:	52800401 	mov	w1, #0x20                  	// #32
   23c30:	91000063 	add	x3, x3, #0x0
			23c30: R_AARCH64_ADD_ABS_LO12_NC	.text+0x23c14
   23c34:	94000000 	bl	0 <log_post_write_mmio>
			23c34: R_AARCH64_CALL26	log_post_write_mmio
   23c38:	17ffffbd 	b	23b2c <vfe_isr_wm_done+0x12c>
   23c3c:	aa1703fe 	mov	x30, x23
   23c40:	d50320ff 	xpaclri
   23c44:	aa1b03e2 	mov	x2, x27
   23c48:	aa1e03e4 	mov	x4, x30
   23c4c:	2a1c03e0 	mov	w0, w28
   23c50:	90000003 	adrp	x3, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			23c50: R_AARCH64_ADR_PREL_PG_HI21	.text+0x23c3c
   23c54:	52800401 	mov	w1, #0x20                  	// #32
   23c58:	91000063 	add	x3, x3, #0x0
			23c58: R_AARCH64_ADD_ABS_LO12_NC	.text+0x23c3c
   23c5c:	b9006ffc 	str	w28, [sp, #108]
   23c60:	94000000 	bl	0 <log_write_mmio>
			23c60: R_AARCH64_CALL26	log_write_mmio
   23c64:	b9406fe5 	ldr	w5, [sp, #108]
   23c68:	17ffffaf 	b	23b24 <vfe_isr_wm_done+0x124>
   23c6c:	90000001 	adrp	x1, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			23c6c: R_AARCH64_ADR_PREL_PG_HI21	.rodata+0x3d2a0
   23c70:	90000000 	adrp	x0, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			23c70: R_AARCH64_ADR_PREL_PG_HI21	.data+0x1b20
   23c74:	91000021 	add	x1, x1, #0x0
			23c74: R_AARCH64_ADD_ABS_LO12_NC	.rodata+0x3d2a0
   23c78:	91000000 	add	x0, x0, #0x0
			23c78: R_AARCH64_ADD_ABS_LO12_NC	.data+0x1b20
   23c7c:	91012021 	add	x1, x1, #0x48
   23c80:	9103a000 	add	x0, x0, #0xe8
   23c84:	94000000 	bl	0 <___ratelimit>
			23c84: R_AARCH64_CALL26	___ratelimit
   23c88:	350003c0 	cbnz	w0, 23d00 <vfe_isr_wm_done+0x300>
   23c8c:	aa1603e1 	mov	x1, x22
   23c90:	aa1903e0 	mov	x0, x25
   23c94:	94000000 	bl	0 <_raw_spin_unlock_irqrestore>
			23c94: R_AARCH64_CALL26	_raw_spin_unlock_irqrestore
   23c98:	a94153f3 	ldp	x19, x20, [sp, #16]
   23c9c:	a9425bf5 	ldp	x21, x22, [sp, #32]
   23ca0:	a94363f7 	ldp	x23, x24, [sp, #48]
   23ca4:	a9446bf9 	ldp	x25, x26, [sp, #64]
   23ca8:	f85f8e5e 	ldr	x30, [x18, #-8]!
   23cac:	f84707fd 	ldr	x29, [sp], #112
   23cb0:	d50323bf 	autiasp
   23cb4:	d2800000 	mov	x0, #0x0                   	// #0
   23cb8:	d2800001 	mov	x1, #0x0                   	// #0
   23cbc:	d2800002 	mov	x2, #0x0                   	// #0
   23cc0:	d2800003 	mov	x3, #0x0                   	// #0
   23cc4:	d2800004 	mov	x4, #0x0                   	// #0
   23cc8:	d2800005 	mov	x5, #0x0                   	// #0
   23ccc:	d2800010 	mov	x16, #0x0                   	// #0
   23cd0:	d2800011 	mov	x17, #0x0                   	// #0
   23cd4:	d65f03c0 	ret
   23cd8:	90000001 	adrp	x1, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			23cd8: R_AARCH64_ADR_PREL_PG_HI21	.rodata+0x3d2a0
   23cdc:	90000000 	adrp	x0, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			23cdc: R_AARCH64_ADR_PREL_PG_HI21	.data+0x1b20
   23ce0:	91000021 	add	x1, x1, #0x0
			23ce0: R_AARCH64_ADD_ABS_LO12_NC	.rodata+0x3d2a0
   23ce4:	91000000 	add	x0, x0, #0x0
			23ce4: R_AARCH64_ADD_ABS_LO12_NC	.data+0x1b20
   23ce8:	91012021 	add	x1, x1, #0x48
   23cec:	91054000 	add	x0, x0, #0x150
   23cf0:	94000000 	bl	0 <___ratelimit>
			23cf0: R_AARCH64_CALL26	___ratelimit
   23cf4:	35000120 	cbnz	w0, 23d18 <vfe_isr_wm_done+0x318>
   23cf8:	a94573fb 	ldp	x27, x28, [sp, #80]
   23cfc:	17ffffe4 	b	23c8c <vfe_isr_wm_done+0x28c>
   23d00:	f9400260 	ldr	x0, [x19]
   23d04:	90000001 	adrp	x1, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			23d04: R_AARCH64_ADR_PREL_PG_HI21	.rodata.str1.8+0x1e10
   23d08:	91000021 	add	x1, x1, #0x0
			23d08: R_AARCH64_ADD_ABS_LO12_NC	.rodata.str1.8+0x1e10
   23d0c:	f941b000 	ldr	x0, [x0, #864]
   23d10:	94000000 	bl	0 <_dev_err>
			23d10: R_AARCH64_CALL26	_dev_err
   23d14:	17ffffde 	b	23c8c <vfe_isr_wm_done+0x28c>
   23d18:	f9400260 	ldr	x0, [x19]
   23d1c:	90000001 	adrp	x1, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			23d1c: R_AARCH64_ADR_PREL_PG_HI21	.rodata.str1.8+0x1e38
   23d20:	b94b8f62 	ldr	w2, [x27, #2956]
   23d24:	91000021 	add	x1, x1, #0x0
			23d24: R_AARCH64_ADD_ABS_LO12_NC	.rodata.str1.8+0x1e38
   23d28:	f941b000 	ldr	x0, [x0, #864]
   23d2c:	94000000 	bl	0 <_dev_err>
			23d2c: R_AARCH64_CALL26	_dev_err
   23d30:	a94573fb 	ldp	x27, x28, [sp, #80]
   23d34:	17ffffd6 	b	23c8c <vfe_isr_wm_done+0x28c>
   23d38:	90000000 	adrp	x0, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			23d38: R_AARCH64_ADR_PREL_PG_HI21	.data+0x1b20
   23d3c:	91000000 	add	x0, x0, #0x0
			23d3c: R_AARCH64_ADD_ABS_LO12_NC	.data+0x1b20
   23d40:	91032000 	add	x0, x0, #0xc8
   23d44:	aa1a03e1 	mov	x1, x26
   23d48:	94000000 	bl	0 <__ubsan_handle_out_of_bounds>
			23d48: R_AARCH64_CALL26	__ubsan_handle_out_of_bounds
   23d4c:	17ffff49 	b	23a70 <vfe_isr_wm_done+0x70>
   23d50:	90000000 	adrp	x0, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			23d50: R_AARCH64_ADR_PREL_PG_HI21	.data+0x1b20
   23d54:	91000000 	add	x0, x0, #0x0
			23d54: R_AARCH64_ADD_ABS_LO12_NC	.data+0x1b20
   23d58:	9102a000 	add	x0, x0, #0xa8
   23d5c:	aa1503e1 	mov	x1, x21
   23d60:	94000000 	bl	0 <__ubsan_handle_out_of_bounds>
			23d60: R_AARCH64_CALL26	__ubsan_handle_out_of_bounds
   23d64:	17ffff3b 	b	23a50 <vfe_isr_wm_done+0x50>
   23d68:	90000000 	adrp	x0, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			23d68: R_AARCH64_ADR_PREL_PG_HI21	.data+0x1b20
   23d6c:	91000000 	add	x0, x0, #0x0
			23d6c: R_AARCH64_ADD_ABS_LO12_NC	.data+0x1b20
   23d70:	91022000 	add	x0, x0, #0x88
   23d74:	aa1a03e1 	mov	x1, x26
   23d78:	94000000 	bl	0 <__ubsan_handle_out_of_bounds>
			23d78: R_AARCH64_CALL26	__ubsan_handle_out_of_bounds
   23d7c:	17ffff31 	b	23a40 <vfe_isr_wm_done+0x40>
   23d80:	90000000 	adrp	x0, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			23d80: R_AARCH64_ADR_PREL_PG_HI21	.data+0x1b20
   23d84:	91000000 	add	x0, x0, #0x0
			23d84: R_AARCH64_ADD_ABS_LO12_NC	.data+0x1b20
   23d88:	9104c000 	add	x0, x0, #0x130
   23d8c:	aa1403e1 	mov	x1, x20
   23d90:	94000000 	bl	0 <__ubsan_handle_out_of_bounds>
			23d90: R_AARCH64_CALL26	__ubsan_handle_out_of_bounds
   23d94:	17ffff40 	b	23a94 <vfe_isr_wm_done+0x94>
   23d98:	90000000 	adrp	x0, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			23d98: R_AARCH64_ADR_PREL_PG_HI21	.data+0x1b20
   23d9c:	91000000 	add	x0, x0, #0x0
			23d9c: R_AARCH64_ADD_ABS_LO12_NC	.data+0x1b20
   23da0:	aa1a03e1 	mov	x1, x26
   23da4:	91044000 	add	x0, x0, #0x110
   23da8:	94000000 	bl	0 <__ubsan_handle_out_of_bounds>
			23da8: R_AARCH64_CALL26	__ubsan_handle_out_of_bounds
   23dac:	17ffff37 	b	23a88 <vfe_isr_wm_done+0x88>

Disassembly of section .init.text:

Disassembly of section .exit.text:

Disassembly of section .plt:

Disassembly of section .text.ftrace_trampoline:
