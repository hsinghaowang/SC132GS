
/home/ubuntu/sc132gs-camera-tests/integer-fps-20261007/camss-inspection.ko:     file format elf64-littleaarch64


Disassembly of section .text:

0000000000025bc0 <vfe_wm_start>:
   25bc0:	d503201f 	nop
   25bc4:	d503201f 	nop
   25bc8:	d503233f 	paciasp
   25bcc:	f800865e 	str	x30, [x18], #8
   25bd0:	a9bb7bfd 	stp	x29, x30, [sp, #-80]!
   25bd4:	910003fd 	mov	x29, sp
   25bd8:	a90153f3 	stp	x19, x20, [sp, #16]
   25bdc:	aa0003f3 	mov	x19, x0
   25be0:	528002f4 	mov	w20, #0x17                  	// #23
   25be4:	a9025bf5 	stp	x21, x22, [sp, #32]
   25be8:	aa1e03f5 	mov	x21, x30
   25bec:	a90363f7 	stp	x23, x24, [sp, #48]
   25bf0:	12001c38 	and	w24, w1, #0xff
   25bf4:	aa0203f7 	mov	x23, x2
   25bf8:	f90023f9 	str	x25, [sp, #64]
   25bfc:	94000000 	bl	2cfc0 <vfe_is_lite>
			25bfc: R_AARCH64_CALL26	vfe_is_lite
   25c00:	f240001f 	tst	x0, #0x1
   25c04:	aa1303e0 	mov	x0, x19
   25c08:	f9400a76 	ldr	x22, [x19, #16]
   25c0c:	1a9f0294 	csel	w20, w20, wzr, eq	// eq = none
   25c10:	94000000 	bl	2cfc0 <vfe_is_lite>
			25c10: R_AARCH64_CALL26	vfe_is_lite
   25c14:	f240001f 	tst	x0, #0x1
   25c18:	0b180294 	add	w20, w20, w24
   25c1c:	d2954101 	mov	x1, #0xaa08                	// #43528
   25c20:	d2834102 	mov	x2, #0x1a08                	// #6664
   25c24:	9a820021 	csel	x1, x1, x2, eq	// eq = none
   25c28:	12001e94 	and	w20, w20, #0xff
   25c2c:	8b0102d6 	add	x22, x22, x1
   25c30:	d503201f 	nop
   25c34:	12bf8000 	mov	w0, #0x3ffffff             	// #67108863
   25c38:	b90002c0 	str	w0, [x22]
   25c3c:	d503201f 	nop
   25c40:	f9400a76 	ldr	x22, [x19, #16]
   25c44:	aa1303e0 	mov	x0, x19
   25c48:	94000000 	bl	2cfc0 <vfe_is_lite>
			25c48: R_AARCH64_CALL26	vfe_is_lite
   25c4c:	f240001f 	tst	x0, #0x1
   25c50:	d2955b81 	mov	x1, #0xaadc                	// #43740
   25c54:	d2835b82 	mov	x2, #0x1adc                	// #6876
   25c58:	9a820021 	csel	x1, x1, x2, eq	// eq = none
   25c5c:	8b0102d6 	add	x22, x22, x1
   25c60:	d503201f 	nop
   25c64:	b90002df 	str	wzr, [x22]
   25c68:	d503201f 	nop
   25c6c:	b948fee1 	ldr	w1, [x23, #2300]
   25c70:	aa1303e0 	mov	x0, x19
   25c74:	b94912f8 	ldr	w24, [x23, #2320]
   25c78:	53185e94 	lsl	w20, w20, #8
   25c7c:	f9400a79 	ldr	x25, [x19, #16]
   25c80:	52958116 	mov	w22, #0xac08                	// #44040
   25c84:	9123e2f7 	add	x23, x23, #0x8f8
   25c88:	1b017f18 	mul	w24, w24, w1
   25c8c:	94000000 	bl	2cfc0 <vfe_is_lite>
			25c8c: R_AARCH64_CALL26	vfe_is_lite
   25c90:	f240001f 	tst	x0, #0x1
   25c94:	52838101 	mov	w1, #0x1c08                	// #7176
   25c98:	1a8102d6 	csel	w22, w22, w1, eq	// eq = none
   25c9c:	0b160296 	add	w22, w20, w22
   25ca0:	8b364336 	add	x22, x25, w22, uxtw
   25ca4:	d503201f 	nop
   25ca8:	b90002d8 	str	w24, [x22]
   25cac:	d503201f 	nop
   25cb0:	f9400a78 	ldr	x24, [x19, #16]
   25cb4:	aa1303e0 	mov	x0, x19
   25cb8:	94000000 	bl	2cfc0 <vfe_is_lite>
			25cb8: R_AARCH64_CALL26	vfe_is_lite
   25cbc:	f240001f 	tst	x0, #0x1
   25cc0:	52958c96 	mov	w22, #0xac64                	// #44132
   25cc4:	52838c81 	mov	w1, #0x1c64                	// #7268
   25cc8:	1a8102d6 	csel	w22, w22, w1, eq	// eq = none
   25ccc:	0b160296 	add	w22, w20, w22
   25cd0:	8b364316 	add	x22, x24, w22, uxtw
   25cd4:	d503201f 	nop
   25cd8:	528001e0 	mov	w0, #0xf                   	// #15
   25cdc:	b90002c0 	str	w0, [x22]
   25ce0:	d503201f 	nop
   25ce4:	f9400a78 	ldr	x24, [x19, #16]
   25ce8:	aa1303e0 	mov	x0, x19
   25cec:	94000000 	bl	2cfc0 <vfe_is_lite>
			25cec: R_AARCH64_CALL26	vfe_is_lite
   25cf0:	f240001f 	tst	x0, #0x1
   25cf4:	52958196 	mov	w22, #0xac0c                	// #44044
   25cf8:	52838181 	mov	w1, #0x1c0c                	// #7180
   25cfc:	1a8102d6 	csel	w22, w22, w1, eq	// eq = none
   25d00:	0b160296 	add	w22, w20, w22
   25d04:	8b364316 	add	x22, x24, w22, uxtw
   25d08:	d503201f 	nop
   25d0c:	529fffe0 	mov	w0, #0xffff                	// #65535
   25d10:	b90002c0 	str	w0, [x22]
   25d14:	d503201f 	nop
   25d18:	f9400a78 	ldr	x24, [x19, #16]
   25d1c:	aa1303e0 	mov	x0, x19
   25d20:	b9401af7 	ldr	w23, [x23, #24]
   25d24:	94000000 	bl	2cfc0 <vfe_is_lite>
			25d24: R_AARCH64_CALL26	vfe_is_lite
   25d28:	f240001f 	tst	x0, #0x1
   25d2c:	52958296 	mov	w22, #0xac14                	// #44052
   25d30:	52838281 	mov	w1, #0x1c14                	// #7188
   25d34:	1a8102d6 	csel	w22, w22, w1, eq	// eq = none
   25d38:	0b160296 	add	w22, w20, w22
   25d3c:	8b364316 	add	x22, x24, w22, uxtw
   25d40:	d503201f 	nop
   25d44:	b90002d7 	str	w23, [x22]
   25d48:	d503201f 	nop
   25d4c:	f9400a77 	ldr	x23, [x19, #16]
   25d50:	aa1303e0 	mov	x0, x19
   25d54:	94000000 	bl	2cfc0 <vfe_is_lite>
			25d54: R_AARCH64_CALL26	vfe_is_lite
   25d58:	f240001f 	tst	x0, #0x1
   25d5c:	52958316 	mov	w22, #0xac18                	// #44056
   25d60:	52838301 	mov	w1, #0x1c18                	// #7192
   25d64:	1a8102d6 	csel	w22, w22, w1, eq	// eq = none
   25d68:	0b160296 	add	w22, w20, w22
   25d6c:	8b3642f6 	add	x22, x23, w22, uxtw
   25d70:	d503201f 	nop
   25d74:	b90002df 	str	wzr, [x22]
   25d78:	d503201f 	nop
   25d7c:	f9400a77 	ldr	x23, [x19, #16]
   25d80:	aa1303e0 	mov	x0, x19
   25d84:	94000000 	bl	2cfc0 <vfe_is_lite>
			25d84: R_AARCH64_CALL26	vfe_is_lite
   25d88:	f240001f 	tst	x0, #0x1
   25d8c:	52958716 	mov	w22, #0xac38                	// #44088
   25d90:	52838701 	mov	w1, #0x1c38                	// #7224
   25d94:	1a8102d6 	csel	w22, w22, w1, eq	// eq = none
   25d98:	0b160296 	add	w22, w20, w22
   25d9c:	8b3642f6 	add	x22, x23, w22, uxtw
   25da0:	d503201f 	nop
   25da4:	b90002df 	str	wzr, [x22]
   25da8:	d503201f 	nop
   25dac:	f9400a77 	ldr	x23, [x19, #16]
   25db0:	aa1303e0 	mov	x0, x19
   25db4:	94000000 	bl	2cfc0 <vfe_is_lite>
			25db4: R_AARCH64_CALL26	vfe_is_lite
   25db8:	f240001f 	tst	x0, #0x1
   25dbc:	52958796 	mov	w22, #0xac3c                	// #44092
   25dc0:	52838781 	mov	w1, #0x1c3c                	// #7228
   25dc4:	1a8102d6 	csel	w22, w22, w1, eq	// eq = none
   25dc8:	0b160296 	add	w22, w20, w22
   25dcc:	8b3642f6 	add	x22, x23, w22, uxtw
   25dd0:	d503201f 	nop
   25dd4:	52800020 	mov	w0, #0x1                   	// #1
   25dd8:	b90002c0 	str	w0, [x22]
   25ddc:	d503201f 	nop
   25de0:	f9400a77 	ldr	x23, [x19, #16]
   25de4:	aa1303e0 	mov	x0, x19
   25de8:	94000000 	bl	2cfc0 <vfe_is_lite>
			25de8: R_AARCH64_CALL26	vfe_is_lite
   25dec:	f240001f 	tst	x0, #0x1
   25df0:	52958616 	mov	w22, #0xac30                	// #44080
   25df4:	52838601 	mov	w1, #0x1c30                	// #7216
   25df8:	1a8102d6 	csel	w22, w22, w1, eq	// eq = none
   25dfc:	0b160296 	add	w22, w20, w22
   25e00:	8b3642f6 	add	x22, x23, w22, uxtw
   25e04:	d503201f 	nop
   25e08:	b90002df 	str	wzr, [x22]
   25e0c:	d503201f 	nop
   25e10:	f9400a77 	ldr	x23, [x19, #16]
   25e14:	aa1303e0 	mov	x0, x19
   25e18:	94000000 	bl	2cfc0 <vfe_is_lite>
			25e18: R_AARCH64_CALL26	vfe_is_lite
   25e1c:	f240001f 	tst	x0, #0x1
   25e20:	52958696 	mov	w22, #0xac34                	// #44084
   25e24:	52838681 	mov	w1, #0x1c34                	// #7220
   25e28:	1a8102d6 	csel	w22, w22, w1, eq	// eq = none
   25e2c:	0b160296 	add	w22, w20, w22
   25e30:	8b3642f6 	add	x22, x23, w22, uxtw
   25e34:	d503201f 	nop
   25e38:	52800020 	mov	w0, #0x1                   	// #1
   25e3c:	b90002c0 	str	w0, [x22]
   25e40:	d503201f 	nop
   25e44:	f9400a76 	ldr	x22, [x19, #16]
   25e48:	aa1303e0 	mov	x0, x19
   25e4c:	94000000 	bl	2cfc0 <vfe_is_lite>
			25e4c: R_AARCH64_CALL26	vfe_is_lite
   25e50:	f240001f 	tst	x0, #0x1
   25e54:	52958001 	mov	w1, #0xac00                	// #44032
   25e58:	52838002 	mov	w2, #0x1c00                	// #7168
   25e5c:	1a820021 	csel	w1, w1, w2, eq	// eq = none
   25e60:	0b010294 	add	w20, w20, w1
   25e64:	8b3442d4 	add	x20, x22, w20, uxtw
   25e68:	d503201f 	nop
   25e6c:	320083e0 	mov	w0, #0x10001               	// #65537
   25e70:	b9000280 	str	w0, [x20]
   25e74:	d503201f 	nop
   25e78:	f85f8e5e 	ldr	x30, [x18, #-8]!
   25e7c:	a94153f3 	ldp	x19, x20, [sp, #16]
   25e80:	a9425bf5 	ldp	x21, x22, [sp, #32]
   25e84:	a94363f7 	ldp	x23, x24, [sp, #48]
   25e88:	f94023f9 	ldr	x25, [sp, #64]
   25e8c:	f84507fd 	ldr	x29, [sp], #80
   25e90:	d50323bf 	autiasp
   25e94:	d2800000 	mov	x0, #0x0                   	// #0
   25e98:	d2800001 	mov	x1, #0x0                   	// #0
   25e9c:	d2800002 	mov	x2, #0x0                   	// #0
   25ea0:	d2800003 	mov	x3, #0x0                   	// #0
   25ea4:	d2800004 	mov	x4, #0x0                   	// #0
   25ea8:	d2800010 	mov	x16, #0x0                   	// #0
   25eac:	d2800011 	mov	x17, #0x0                   	// #0
   25eb0:	d65f03c0 	ret
   25eb4:	aa1503fe 	mov	x30, x21
   25eb8:	d50320ff 	xpaclri
   25ebc:	aa1603e2 	mov	x2, x22
   25ec0:	aa1e03e4 	mov	x4, x30
   25ec4:	90000003 	adrp	x3, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			25ec4: R_AARCH64_ADR_PREL_PG_HI21	.text+0x25eb4
   25ec8:	52800401 	mov	w1, #0x20                  	// #32
   25ecc:	91000063 	add	x3, x3, #0x0
			25ecc: R_AARCH64_ADD_ABS_LO12_NC	.text+0x25eb4
   25ed0:	b24067e0 	mov	x0, #0x3ffffff             	// #67108863
   25ed4:	94000000 	bl	0 <log_write_mmio>
			25ed4: R_AARCH64_CALL26	log_write_mmio
   25ed8:	17ffff57 	b	25c34 <vfe_wm_start+0x74>
   25edc:	aa1503fe 	mov	x30, x21
   25ee0:	d50320ff 	xpaclri
   25ee4:	aa1403e2 	mov	x2, x20
   25ee8:	aa1e03e4 	mov	x4, x30
   25eec:	52800401 	mov	w1, #0x20                  	// #32
   25ef0:	320083e0 	mov	w0, #0x10001               	// #65537
   25ef4:	90000003 	adrp	x3, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			25ef4: R_AARCH64_ADR_PREL_PG_HI21	.text+0x25edc
   25ef8:	91000063 	add	x3, x3, #0x0
			25ef8: R_AARCH64_ADD_ABS_LO12_NC	.text+0x25edc
   25efc:	94000000 	bl	0 <log_post_write_mmio>
			25efc: R_AARCH64_CALL26	log_post_write_mmio
   25f00:	f85f8e5e 	ldr	x30, [x18, #-8]!
   25f04:	a94153f3 	ldp	x19, x20, [sp, #16]
   25f08:	a9425bf5 	ldp	x21, x22, [sp, #32]
   25f0c:	a94363f7 	ldp	x23, x24, [sp, #48]
   25f10:	f94023f9 	ldr	x25, [sp, #64]
   25f14:	f84507fd 	ldr	x29, [sp], #80
   25f18:	d50323bf 	autiasp
   25f1c:	d2800000 	mov	x0, #0x0                   	// #0
   25f20:	d2800001 	mov	x1, #0x0                   	// #0
   25f24:	d2800002 	mov	x2, #0x0                   	// #0
   25f28:	d2800003 	mov	x3, #0x0                   	// #0
   25f2c:	d2800004 	mov	x4, #0x0                   	// #0
   25f30:	d2800010 	mov	x16, #0x0                   	// #0
   25f34:	d2800011 	mov	x17, #0x0                   	// #0
   25f38:	d65f03c0 	ret
   25f3c:	aa1503fe 	mov	x30, x21
   25f40:	d50320ff 	xpaclri
   25f44:	aa1403e2 	mov	x2, x20
   25f48:	aa1e03e4 	mov	x4, x30
   25f4c:	90000003 	adrp	x3, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			25f4c: R_AARCH64_ADR_PREL_PG_HI21	.text+0x25f3c
   25f50:	52800401 	mov	w1, #0x20                  	// #32
   25f54:	91000063 	add	x3, x3, #0x0
			25f54: R_AARCH64_ADD_ABS_LO12_NC	.text+0x25f3c
   25f58:	320083e0 	mov	w0, #0x10001               	// #65537
   25f5c:	94000000 	bl	0 <log_write_mmio>
			25f5c: R_AARCH64_CALL26	log_write_mmio
   25f60:	17ffffc3 	b	25e6c <vfe_wm_start+0x2ac>
   25f64:	aa1503fe 	mov	x30, x21
   25f68:	d50320ff 	xpaclri
   25f6c:	aa1603e2 	mov	x2, x22
   25f70:	aa1e03e4 	mov	x4, x30
   25f74:	90000003 	adrp	x3, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			25f74: R_AARCH64_ADR_PREL_PG_HI21	.text+0x25f64
   25f78:	52800401 	mov	w1, #0x20                  	// #32
   25f7c:	91000063 	add	x3, x3, #0x0
			25f7c: R_AARCH64_ADD_ABS_LO12_NC	.text+0x25f64
   25f80:	d2800020 	mov	x0, #0x1                   	// #1
   25f84:	94000000 	bl	0 <log_post_write_mmio>
			25f84: R_AARCH64_CALL26	log_post_write_mmio
   25f88:	17ffffaf 	b	25e44 <vfe_wm_start+0x284>
   25f8c:	aa1503fe 	mov	x30, x21
   25f90:	d50320ff 	xpaclri
   25f94:	aa1603e2 	mov	x2, x22
   25f98:	aa1e03e4 	mov	x4, x30
   25f9c:	90000003 	adrp	x3, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			25f9c: R_AARCH64_ADR_PREL_PG_HI21	.text+0x25f8c
   25fa0:	52800401 	mov	w1, #0x20                  	// #32
   25fa4:	91000063 	add	x3, x3, #0x0
			25fa4: R_AARCH64_ADD_ABS_LO12_NC	.text+0x25f8c
   25fa8:	d2800020 	mov	x0, #0x1                   	// #1
   25fac:	94000000 	bl	0 <log_write_mmio>
			25fac: R_AARCH64_CALL26	log_write_mmio
   25fb0:	17ffffa2 	b	25e38 <vfe_wm_start+0x278>
   25fb4:	aa1503fe 	mov	x30, x21
   25fb8:	d50320ff 	xpaclri
   25fbc:	aa1603e2 	mov	x2, x22
   25fc0:	aa1e03e4 	mov	x4, x30
   25fc4:	90000003 	adrp	x3, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			25fc4: R_AARCH64_ADR_PREL_PG_HI21	.text+0x25fb4
   25fc8:	52800401 	mov	w1, #0x20                  	// #32
   25fcc:	91000063 	add	x3, x3, #0x0
			25fcc: R_AARCH64_ADD_ABS_LO12_NC	.text+0x25fb4
   25fd0:	d2800000 	mov	x0, #0x0                   	// #0
   25fd4:	94000000 	bl	0 <log_post_write_mmio>
			25fd4: R_AARCH64_CALL26	log_post_write_mmio
   25fd8:	17ffff8e 	b	25e10 <vfe_wm_start+0x250>
   25fdc:	aa1503fe 	mov	x30, x21
   25fe0:	d50320ff 	xpaclri
   25fe4:	aa1603e2 	mov	x2, x22
   25fe8:	aa1e03e4 	mov	x4, x30
   25fec:	90000003 	adrp	x3, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			25fec: R_AARCH64_ADR_PREL_PG_HI21	.text+0x25fdc
   25ff0:	52800401 	mov	w1, #0x20                  	// #32
   25ff4:	91000063 	add	x3, x3, #0x0
			25ff4: R_AARCH64_ADD_ABS_LO12_NC	.text+0x25fdc
   25ff8:	d2800000 	mov	x0, #0x0                   	// #0
   25ffc:	94000000 	bl	0 <log_write_mmio>
			25ffc: R_AARCH64_CALL26	log_write_mmio
   26000:	17ffff82 	b	25e08 <vfe_wm_start+0x248>
   26004:	aa1503fe 	mov	x30, x21
   26008:	d50320ff 	xpaclri
   2600c:	aa1603e2 	mov	x2, x22
   26010:	aa1e03e4 	mov	x4, x30
   26014:	90000003 	adrp	x3, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			26014: R_AARCH64_ADR_PREL_PG_HI21	.text+0x26004
   26018:	52800401 	mov	w1, #0x20                  	// #32
   2601c:	91000063 	add	x3, x3, #0x0
			2601c: R_AARCH64_ADD_ABS_LO12_NC	.text+0x26004
   26020:	d2800020 	mov	x0, #0x1                   	// #1
   26024:	94000000 	bl	0 <log_post_write_mmio>
			26024: R_AARCH64_CALL26	log_post_write_mmio
   26028:	17ffff6e 	b	25de0 <vfe_wm_start+0x220>
   2602c:	aa1503fe 	mov	x30, x21
   26030:	d50320ff 	xpaclri
   26034:	aa1603e2 	mov	x2, x22
   26038:	aa1e03e4 	mov	x4, x30
   2603c:	90000003 	adrp	x3, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			2603c: R_AARCH64_ADR_PREL_PG_HI21	.text+0x2602c
   26040:	52800401 	mov	w1, #0x20                  	// #32
   26044:	91000063 	add	x3, x3, #0x0
			26044: R_AARCH64_ADD_ABS_LO12_NC	.text+0x2602c
   26048:	d2800020 	mov	x0, #0x1                   	// #1
   2604c:	94000000 	bl	0 <log_write_mmio>
			2604c: R_AARCH64_CALL26	log_write_mmio
   26050:	17ffff61 	b	25dd4 <vfe_wm_start+0x214>
   26054:	aa1503fe 	mov	x30, x21
   26058:	d50320ff 	xpaclri
   2605c:	aa1603e2 	mov	x2, x22
   26060:	aa1e03e4 	mov	x4, x30
   26064:	90000003 	adrp	x3, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			26064: R_AARCH64_ADR_PREL_PG_HI21	.text+0x26054
   26068:	52800401 	mov	w1, #0x20                  	// #32
   2606c:	91000063 	add	x3, x3, #0x0
			2606c: R_AARCH64_ADD_ABS_LO12_NC	.text+0x26054
   26070:	d2800000 	mov	x0, #0x0                   	// #0
   26074:	94000000 	bl	0 <log_post_write_mmio>
			26074: R_AARCH64_CALL26	log_post_write_mmio
   26078:	17ffff4d 	b	25dac <vfe_wm_start+0x1ec>
   2607c:	aa1503fe 	mov	x30, x21
   26080:	d50320ff 	xpaclri
   26084:	aa1603e2 	mov	x2, x22
   26088:	aa1e03e4 	mov	x4, x30
   2608c:	90000003 	adrp	x3, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			2608c: R_AARCH64_ADR_PREL_PG_HI21	.text+0x2607c
   26090:	52800401 	mov	w1, #0x20                  	// #32
   26094:	91000063 	add	x3, x3, #0x0
			26094: R_AARCH64_ADD_ABS_LO12_NC	.text+0x2607c
   26098:	d2800000 	mov	x0, #0x0                   	// #0
   2609c:	94000000 	bl	0 <log_write_mmio>
			2609c: R_AARCH64_CALL26	log_write_mmio
   260a0:	17ffff41 	b	25da4 <vfe_wm_start+0x1e4>
   260a4:	aa1503fe 	mov	x30, x21
   260a8:	d50320ff 	xpaclri
   260ac:	aa1603e2 	mov	x2, x22
   260b0:	aa1e03e4 	mov	x4, x30
   260b4:	90000003 	adrp	x3, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			260b4: R_AARCH64_ADR_PREL_PG_HI21	.text+0x260a4
   260b8:	52800401 	mov	w1, #0x20                  	// #32
   260bc:	91000063 	add	x3, x3, #0x0
			260bc: R_AARCH64_ADD_ABS_LO12_NC	.text+0x260a4
   260c0:	d2800000 	mov	x0, #0x0                   	// #0
   260c4:	94000000 	bl	0 <log_post_write_mmio>
			260c4: R_AARCH64_CALL26	log_post_write_mmio
   260c8:	17ffff2d 	b	25d7c <vfe_wm_start+0x1bc>
   260cc:	aa1503fe 	mov	x30, x21
   260d0:	d50320ff 	xpaclri
   260d4:	aa1603e2 	mov	x2, x22
   260d8:	aa1e03e4 	mov	x4, x30
   260dc:	90000003 	adrp	x3, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			260dc: R_AARCH64_ADR_PREL_PG_HI21	.text+0x260cc
   260e0:	52800401 	mov	w1, #0x20                  	// #32
   260e4:	91000063 	add	x3, x3, #0x0
			260e4: R_AARCH64_ADD_ABS_LO12_NC	.text+0x260cc
   260e8:	d2800000 	mov	x0, #0x0                   	// #0
   260ec:	94000000 	bl	0 <log_write_mmio>
			260ec: R_AARCH64_CALL26	log_write_mmio
   260f0:	17ffff21 	b	25d74 <vfe_wm_start+0x1b4>
   260f4:	aa1503fe 	mov	x30, x21
   260f8:	d50320ff 	xpaclri
   260fc:	aa1603e2 	mov	x2, x22
   26100:	aa1e03e4 	mov	x4, x30
   26104:	2a1703e0 	mov	w0, w23
   26108:	90000003 	adrp	x3, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			26108: R_AARCH64_ADR_PREL_PG_HI21	.text+0x260f4
   2610c:	52800401 	mov	w1, #0x20                  	// #32
   26110:	91000063 	add	x3, x3, #0x0
			26110: R_AARCH64_ADD_ABS_LO12_NC	.text+0x260f4
   26114:	94000000 	bl	0 <log_post_write_mmio>
			26114: R_AARCH64_CALL26	log_post_write_mmio
   26118:	17ffff0d 	b	25d4c <vfe_wm_start+0x18c>
   2611c:	aa1503fe 	mov	x30, x21
   26120:	d50320ff 	xpaclri
   26124:	aa1603e2 	mov	x2, x22
   26128:	aa1e03e4 	mov	x4, x30
   2612c:	2a1703e0 	mov	w0, w23
   26130:	90000003 	adrp	x3, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			26130: R_AARCH64_ADR_PREL_PG_HI21	.text+0x2611c
   26134:	52800401 	mov	w1, #0x20                  	// #32
   26138:	91000063 	add	x3, x3, #0x0
			26138: R_AARCH64_ADD_ABS_LO12_NC	.text+0x2611c
   2613c:	94000000 	bl	0 <log_write_mmio>
			2613c: R_AARCH64_CALL26	log_write_mmio
   26140:	17ffff01 	b	25d44 <vfe_wm_start+0x184>
   26144:	aa1503fe 	mov	x30, x21
   26148:	d50320ff 	xpaclri
   2614c:	aa1603e2 	mov	x2, x22
   26150:	aa1e03e4 	mov	x4, x30
   26154:	90000003 	adrp	x3, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			26154: R_AARCH64_ADR_PREL_PG_HI21	.text+0x26144
   26158:	52800401 	mov	w1, #0x20                  	// #32
   2615c:	91000063 	add	x3, x3, #0x0
			2615c: R_AARCH64_ADD_ABS_LO12_NC	.text+0x26144
   26160:	d29fffe0 	mov	x0, #0xffff                	// #65535
   26164:	94000000 	bl	0 <log_post_write_mmio>
			26164: R_AARCH64_CALL26	log_post_write_mmio
   26168:	17fffeec 	b	25d18 <vfe_wm_start+0x158>
   2616c:	aa1503fe 	mov	x30, x21
   26170:	d50320ff 	xpaclri
   26174:	aa1603e2 	mov	x2, x22
   26178:	aa1e03e4 	mov	x4, x30
   2617c:	90000003 	adrp	x3, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			2617c: R_AARCH64_ADR_PREL_PG_HI21	.text+0x2616c
   26180:	52800401 	mov	w1, #0x20                  	// #32
   26184:	91000063 	add	x3, x3, #0x0
			26184: R_AARCH64_ADD_ABS_LO12_NC	.text+0x2616c
   26188:	d29fffe0 	mov	x0, #0xffff                	// #65535
   2618c:	94000000 	bl	0 <log_write_mmio>
			2618c: R_AARCH64_CALL26	log_write_mmio
   26190:	17fffedf 	b	25d0c <vfe_wm_start+0x14c>
   26194:	aa1503fe 	mov	x30, x21
   26198:	d50320ff 	xpaclri
   2619c:	aa1603e2 	mov	x2, x22
   261a0:	aa1e03e4 	mov	x4, x30
   261a4:	90000003 	adrp	x3, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			261a4: R_AARCH64_ADR_PREL_PG_HI21	.text+0x26194
   261a8:	52800401 	mov	w1, #0x20                  	// #32
   261ac:	91000063 	add	x3, x3, #0x0
			261ac: R_AARCH64_ADD_ABS_LO12_NC	.text+0x26194
   261b0:	d28001e0 	mov	x0, #0xf                   	// #15
   261b4:	94000000 	bl	0 <log_post_write_mmio>
			261b4: R_AARCH64_CALL26	log_post_write_mmio
   261b8:	17fffecb 	b	25ce4 <vfe_wm_start+0x124>
   261bc:	aa1503fe 	mov	x30, x21
   261c0:	d50320ff 	xpaclri
   261c4:	aa1603e2 	mov	x2, x22
   261c8:	aa1e03e4 	mov	x4, x30
   261cc:	90000003 	adrp	x3, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			261cc: R_AARCH64_ADR_PREL_PG_HI21	.text+0x261bc
   261d0:	52800401 	mov	w1, #0x20                  	// #32
   261d4:	91000063 	add	x3, x3, #0x0
			261d4: R_AARCH64_ADD_ABS_LO12_NC	.text+0x261bc
   261d8:	d28001e0 	mov	x0, #0xf                   	// #15
   261dc:	94000000 	bl	0 <log_write_mmio>
			261dc: R_AARCH64_CALL26	log_write_mmio
   261e0:	17fffebe 	b	25cd8 <vfe_wm_start+0x118>
   261e4:	aa1503fe 	mov	x30, x21
   261e8:	d50320ff 	xpaclri
   261ec:	aa1603e2 	mov	x2, x22
   261f0:	aa1e03e4 	mov	x4, x30
   261f4:	2a1803e0 	mov	w0, w24
   261f8:	90000003 	adrp	x3, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			261f8: R_AARCH64_ADR_PREL_PG_HI21	.text+0x261e4
   261fc:	52800401 	mov	w1, #0x20                  	// #32
   26200:	91000063 	add	x3, x3, #0x0
			26200: R_AARCH64_ADD_ABS_LO12_NC	.text+0x261e4
   26204:	94000000 	bl	0 <log_post_write_mmio>
			26204: R_AARCH64_CALL26	log_post_write_mmio
   26208:	17fffeaa 	b	25cb0 <vfe_wm_start+0xf0>
   2620c:	aa1503fe 	mov	x30, x21
   26210:	d50320ff 	xpaclri
   26214:	aa1603e2 	mov	x2, x22
   26218:	aa1e03e4 	mov	x4, x30
   2621c:	2a1803e0 	mov	w0, w24
   26220:	90000003 	adrp	x3, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			26220: R_AARCH64_ADR_PREL_PG_HI21	.text+0x2620c
   26224:	52800401 	mov	w1, #0x20                  	// #32
   26228:	91000063 	add	x3, x3, #0x0
			26228: R_AARCH64_ADD_ABS_LO12_NC	.text+0x2620c
   2622c:	94000000 	bl	0 <log_write_mmio>
			2622c: R_AARCH64_CALL26	log_write_mmio
   26230:	17fffe9e 	b	25ca8 <vfe_wm_start+0xe8>
   26234:	aa1503fe 	mov	x30, x21
   26238:	d50320ff 	xpaclri
   2623c:	aa1603e2 	mov	x2, x22
   26240:	aa1e03e4 	mov	x4, x30
   26244:	90000003 	adrp	x3, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			26244: R_AARCH64_ADR_PREL_PG_HI21	.text+0x26234
   26248:	52800401 	mov	w1, #0x20                  	// #32
   2624c:	91000063 	add	x3, x3, #0x0
			2624c: R_AARCH64_ADD_ABS_LO12_NC	.text+0x26234
   26250:	d2800000 	mov	x0, #0x0                   	// #0
   26254:	94000000 	bl	0 <log_post_write_mmio>
			26254: R_AARCH64_CALL26	log_post_write_mmio
   26258:	17fffe85 	b	25c6c <vfe_wm_start+0xac>
   2625c:	aa1503fe 	mov	x30, x21
   26260:	d50320ff 	xpaclri
   26264:	aa1603e2 	mov	x2, x22
   26268:	aa1e03e4 	mov	x4, x30
   2626c:	90000003 	adrp	x3, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			2626c: R_AARCH64_ADR_PREL_PG_HI21	.text+0x2625c
   26270:	52800401 	mov	w1, #0x20                  	// #32
   26274:	91000063 	add	x3, x3, #0x0
			26274: R_AARCH64_ADD_ABS_LO12_NC	.text+0x2625c
   26278:	d2800000 	mov	x0, #0x0                   	// #0
   2627c:	94000000 	bl	0 <log_write_mmio>
			2627c: R_AARCH64_CALL26	log_write_mmio
   26280:	17fffe79 	b	25c64 <vfe_wm_start+0xa4>
   26284:	aa1503fe 	mov	x30, x21
   26288:	d50320ff 	xpaclri
   2628c:	aa1603e2 	mov	x2, x22
   26290:	aa1e03e4 	mov	x4, x30
   26294:	90000003 	adrp	x3, 0 <vfe_parent_dev_ops_get_base_address-0x8>
			26294: R_AARCH64_ADR_PREL_PG_HI21	.text+0x26284
   26298:	52800401 	mov	w1, #0x20                  	// #32
   2629c:	91000063 	add	x3, x3, #0x0
			2629c: R_AARCH64_ADD_ABS_LO12_NC	.text+0x26284
   262a0:	b24067e0 	mov	x0, #0x3ffffff             	// #67108863
   262a4:	94000000 	bl	0 <log_post_write_mmio>
			262a4: R_AARCH64_CALL26	log_post_write_mmio
   262a8:	17fffe66 	b	25c40 <vfe_wm_start+0x80>

Disassembly of section .init.text:

Disassembly of section .exit.text:

Disassembly of section .plt:

Disassembly of section .text.ftrace_trampoline:
