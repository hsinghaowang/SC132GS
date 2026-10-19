
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
#define VFE_HW_VERSION				(0x000)
#define VFE_GLOBAL_RESET_CMD			(0x018)
#define		GLOBAL_RESET_CMD_CORE		BIT(0)
#define		GLOBAL_RESET_CMD_CAMIF		BIT(1)
#define		GLOBAL_RESET_CMD_BUS		BIT(2)
#define		GLOBAL_RESET_CMD_BUS_BDG	BIT(3)
#define		GLOBAL_RESET_CMD_REGISTER	BIT(4)
#define		GLOBAL_RESET_CMD_PM		BIT(5)
#define		GLOBAL_RESET_CMD_BUS_MISR	BIT(6)
#define		GLOBAL_RESET_CMD_TESTGEN	BIT(7)
#define		GLOBAL_RESET_CMD_DSP		BIT(8)
#define		GLOBAL_RESET_CMD_IDLE_CGC	BIT(9)
#define		GLOBAL_RESET_CMD_RDI0		BIT(10)
#define		GLOBAL_RESET_CMD_RDI1		BIT(11)
#define		GLOBAL_RESET_CMD_RDI2		BIT(12)
#define		GLOBAL_RESET_CMD_RDI3		BIT(13)
#define		GLOBAL_RESET_CMD_VFE_DOMAIN	BIT(30)
#define		GLOBAL_RESET_CMD_RESET_BYPASS	BIT(31)
#define VFE_CORE_CFG				(0x050)
#define		CFG_PIXEL_PATTERN_YCBYCR	(0x4)
#define		CFG_PIXEL_PATTERN_YCRYCB	(0x5)
#define		CFG_PIXEL_PATTERN_CBYCRY	(0x6)
#define		CFG_PIXEL_PATTERN_CRYCBY	(0x7)
#define		CFG_COMPOSITE_REG_UPDATE_EN	BIT(4)
#define VFE_IRQ_CMD				(0x058)
#define		CMD_GLOBAL_CLEAR		BIT(0)
#define VFE_IRQ_MASK_0					(0x05c)
#define		MASK_0_CAMIF_SOF			BIT(0)
#define		MASK_0_CAMIF_EOF			BIT(1)
#define		MASK_0_RDI_REG_UPDATE(n)		BIT((n) + 5)
#define		MASK_0_IMAGE_MASTER_n_PING_PONG(n)	BIT((n) + 8)
#define		MASK_0_IMAGE_COMPOSITE_DONE_n(n)	BIT((n) + 25)
#define		MASK_0_RESET_ACK			BIT(31)
#define VFE_IRQ_MASK_1					(0x060)
#define		MASK_1_CAMIF_ERROR			BIT(0)
#define		MASK_1_VIOLATION			BIT(7)
#define		MASK_1_BUS_BDG_HALT_ACK			BIT(8)
#define		MASK_1_IMAGE_MASTER_n_BUS_OVERFLOW(n)	BIT((n) + 9)
#define		MASK_1_RDI_SOF(n)			BIT((n) + 29)
#define VFE_IRQ_CLEAR_0					(0x064)
#define VFE_IRQ_CLEAR_1					(0x068)
#define VFE_IRQ_STATUS_0				(0x06c)
#define		STATUS_0_CAMIF_SOF			BIT(0)
#define		STATUS_0_RDI_REG_UPDATE(n)		BIT((n) + 5)
#define		STATUS_0_IMAGE_MASTER_PING_PONG(n)	BIT((n) + 8)
#define		STATUS_0_IMAGE_COMPOSITE_DONE(n)	BIT((n) + 25)
#define		STATUS_0_RESET_ACK			BIT(31)
#define VFE_IRQ_STATUS_1				(0x070)
#define		STATUS_1_VIOLATION			BIT(7)
#define		STATUS_1_BUS_BDG_HALT_ACK		BIT(8)
#define		STATUS_1_RDI_SOF(n)			BIT((n) + 27)
#define VFE_VIOLATION_STATUS			(0x07c)
#define VFE_CAMIF_CMD				(0x478)
#define		CMD_CLEAR_CAMIF_STATUS		BIT(2)
#define VFE_CAMIF_CFG				(0x47c)
#define		CFG_VSYNC_SYNC_EDGE		(0)
#define			VSYNC_ACTIVE_HIGH	(0)
#define			VSYNC_ACTIVE_LOW	(1)
#define		CFG_HSYNC_SYNC_EDGE		(1)
#define			HSYNC_ACTIVE_HIGH	(0)
#define			HSYNC_ACTIVE_LOW	(1)
#define		CFG_VFE_SUBSAMPLE_ENABLE	BIT(4)
#define		CFG_BUS_SUBSAMPLE_ENABLE	BIT(5)
#define		CFG_VFE_OUTPUT_EN		BIT(6)
#define		CFG_BUS_OUTPUT_EN		BIT(7)
#define		CFG_BINNING_EN			BIT(9)
#define		CFG_FRAME_BASED_EN		BIT(10)
#define		CFG_RAW_CROP_EN			BIT(22)
#define VFE_REG_UPDATE_CMD			(0x4ac)
#define		REG_UPDATE_RDI(n)		BIT(1 + (n))
#define VFE_BUS_IRQ_MASK(n)		(0x2044 + (n) * 4)
#define VFE_BUS_IRQ_CLEAR(n)		(0x2050 + (n) * 4)
#define VFE_BUS_IRQ_STATUS(n)		(0x205c + (n) * 4)
#define		STATUS0_COMP_RESET_DONE		BIT(0)
#define		STATUS0_COMP_REG_UPDATE0_DONE	BIT(1)
#define		STATUS0_COMP_REG_UPDATE1_DONE	BIT(2)
#define		STATUS0_COMP_REG_UPDATE2_DONE	BIT(3)
#define		STATUS0_COMP_REG_UPDATE3_DONE	BIT(4)
#define		STATUS0_COMP_REG_UPDATE_DONE(n)	BIT((n) + 1)
#define		STATUS0_COMP0_BUF_DONE		BIT(5)
#define		STATUS0_COMP1_BUF_DONE		BIT(6)
#define		STATUS0_COMP2_BUF_DONE		BIT(7)
#define		STATUS0_COMP3_BUF_DONE		BIT(8)
#define		STATUS0_COMP4_BUF_DONE		BIT(9)
#define		STATUS0_COMP5_BUF_DONE		BIT(10)
#define		STATUS0_COMP_BUF_DONE(n)	BIT((n) + 5)
#define		STATUS0_COMP_ERROR		BIT(11)
#define		STATUS0_COMP_OVERWRITE		BIT(12)
#define		STATUS0_OVERFLOW		BIT(13)
#define		STATUS0_VIOLATION		BIT(14)
#define		STATUS1_WM_CLIENT_BUF_DONE(n)		BIT(n)
#define		STATUS1_EARLY_DONE			BIT(24)
#define		STATUS2_DUAL_COMP0_BUF_DONE		BIT(0)
#define		STATUS2_DUAL_COMP1_BUF_DONE		BIT(1)
#define		STATUS2_DUAL_COMP2_BUF_DONE		BIT(2)
#define		STATUS2_DUAL_COMP3_BUF_DONE		BIT(3)
#define		STATUS2_DUAL_COMP4_BUF_DONE		BIT(4)
#define		STATUS2_DUAL_COMP5_BUF_DONE		BIT(5)
#define		STATUS2_DUAL_COMP_BUF_DONE(n)		BIT(n)
#define		STATUS2_DUAL_COMP_ERROR			BIT(6)
#define		STATUS2_DUAL_COMP_OVERWRITE		BIT(7)
#define VFE_BUS_IRQ_CLEAR_GLOBAL		(0x2068)
#define VFE_BUS_WM_DEBUG_STATUS_CFG		(0x226c)
#define		DEBUG_STATUS_CFG_STATUS0(n)	BIT(n)
#define		DEBUG_STATUS_CFG_STATUS1(n)	BIT(8 + (n))
#define VFE_BUS_WM_ADDR_SYNC_FRAME_HEADER	(0x2080)
#define VFE_BUS_WM_ADDR_SYNC_NO_SYNC		(0x2084)
#define		BUS_VER2_MAX_CLIENTS (24)
#define		WM_ADDR_NO_SYNC_DEFAULT_VAL \
				((1 << BUS_VER2_MAX_CLIENTS) - 1)
#define VFE_BUS_WM_CGC_OVERRIDE			(0x200c)
#define		WM_CGC_OVERRIDE_ALL		(0xFFFFF)
#define VFE_BUS_WM_TEST_BUS_CTRL		(0x211c)
#define VFE_BUS_WM_STATUS0(n)			(0x2200 + (n) * 0x100)
#define VFE_BUS_WM_STATUS1(n)			(0x2204 + (n) * 0x100)
#define VFE_BUS_WM_CFG(n)			(0x2208 + (n) * 0x100)
#define		WM_CFG_EN			(0)
#define		WM_CFG_MODE			(1)
#define			MODE_QCOM_PLAIN	(0)
#define			MODE_MIPI_RAW	(1)
#define		WM_CFG_VIRTUALFRAME		(2)
#define VFE_BUS_WM_HEADER_ADDR(n)		(0x220c + (n) * 0x100)
#define VFE_BUS_WM_HEADER_CFG(n)		(0x2210 + (n) * 0x100)
#define VFE_BUS_WM_IMAGE_ADDR(n)		(0x2214 + (n) * 0x100)
#define VFE_BUS_WM_IMAGE_ADDR_OFFSET(n)		(0x2218 + (n) * 0x100)
#define VFE_BUS_WM_BUFFER_WIDTH_CFG(n)		(0x221c + (n) * 0x100)
#define		WM_BUFFER_DEFAULT_WIDTH		(0xFF01)
#define VFE_BUS_WM_BUFFER_HEIGHT_CFG(n)		(0x2220 + (n) * 0x100)
#define VFE_BUS_WM_PACKER_CFG(n)		(0x2224 + (n) * 0x100)
#define VFE_BUS_WM_STRIDE(n)			(0x2228 + (n) * 0x100)
#define		WM_STRIDE_DEFAULT_STRIDE	(0xFF01)
#define VFE_BUS_WM_IRQ_SUBSAMPLE_PERIOD(n)	(0x2248 + (n) * 0x100)
#define VFE_BUS_WM_IRQ_SUBSAMPLE_PATTERN(n)	(0x224c + (n) * 0x100)
#define VFE_BUS_WM_FRAMEDROP_PERIOD(n)		(0x2250 + (n) * 0x100)
#define VFE_BUS_WM_FRAMEDROP_PATTERN(n)		(0x2254 + (n) * 0x100)
#define VFE_BUS_WM_FRAME_INC(n)			(0x2258 + (n) * 0x100)
#define VFE_BUS_WM_BURST_LIMIT(n)		(0x225c + (n) * 0x100)

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

static irqreturn_t vfe_isr(int irq, void *dev)
{
	struct vfe_device *vfe = dev;
	u32 status0, status1, vfe_bus_status[VFE_LINE_NUM_MAX];
	int i, wm;

	status0 = readl_relaxed(vfe->base + VFE_IRQ_STATUS_0);
	status1 = readl_relaxed(vfe->base + VFE_IRQ_STATUS_1);

	writel_relaxed(status0, vfe->base + VFE_IRQ_CLEAR_0);
	writel_relaxed(status1, vfe->base + VFE_IRQ_CLEAR_1);

	for (i = VFE_LINE_RDI0; i < vfe->res->line_num; i++) {
		vfe_bus_status[i] = readl_relaxed(vfe->base + VFE_BUS_IRQ_STATUS(i));
		writel_relaxed(vfe_bus_status[i], vfe->base + VFE_BUS_IRQ_CLEAR(i));
	}

	/* Enforce ordering between IRQ reading and interpretation */
	wmb();

	writel_relaxed(CMD_GLOBAL_CLEAR, vfe->base + VFE_IRQ_CMD);
	writel_relaxed(1, vfe->base + VFE_BUS_IRQ_CLEAR_GLOBAL);

	if (status0 & STATUS_0_RESET_ACK)
		vfe->isr_ops.reset_ack(vfe);

	for (i = VFE_LINE_RDI0; i < vfe->res->line_num; i++)
		if (status0 & STATUS_0_RDI_REG_UPDATE(i))
			vfe->isr_ops.reg_update(vfe, i);

	for (i = VFE_LINE_RDI0; i < vfe->res->line_num; i++)
		if (status0 & STATUS_1_RDI_SOF(i))
			vfe->isr_ops.sof(vfe, i);

	for (i = 0; i < MSM_VFE_COMPOSITE_IRQ_NUM; i++)
		if (vfe_bus_status[0] & STATUS0_COMP_BUF_DONE(i))
			vfe->isr_ops.comp_done(vfe, i);

	for (wm = 0; wm < MSM_VFE_IMAGE_MASTERS_NUM; wm++)
		if (status0 & BIT(9))
			if (vfe_bus_status[1] & STATUS1_WM_CLIENT_BUF_DONE(wm))
				vfe->isr_ops.wm_done(vfe, wm);

	return IRQ_HANDLED;
}

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
