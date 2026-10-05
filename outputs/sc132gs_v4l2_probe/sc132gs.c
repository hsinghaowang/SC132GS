// SPDX-License-Identifier: GPL-2.0-only
/* Minimal fixed-mode SC132GS V4L2 sub-device for first RAW10 bring-up. */

#include <linux/clk.h>
#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/i2c.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/regmap.h>
#include <linux/sysfs.h>

#include <media/media-entity.h>
#include <media/v4l2-ctrls.h>
#include <media/v4l2-device.h>
#include <media/v4l2-fwnode.h>
#include <media/v4l2-subdev.h>

#define SC132GS_REG_CHIP_ID       0x3107
#define SC132GS_CHIP_ID           0x0132
#define SC132GS_REG_CTRL_MODE     0x0100
#define SC132GS_MODE_STANDBY      0x00
#define SC132GS_MODE_STREAMING    0x01
#define SC132GS_XCLK_HZ           24000000
#define SC132GS_WIDTH             1088
#define SC132GS_HEIGHT            1280
#define SC132GS_PIXEL_RATE        63000000
#define SC132GS_LINK_FREQ_DEFAULT 600000000UL
#define SC132GS_REG_EXPOSURE_H    0x3e00
#define SC132GS_REG_ANALOGUE_GAIN 0x3e08
#define SC132GS_EXPOSURE_DEFAULT  808
#define SC132GS_EXPOSURE_MAX      2560
#define SC132GS_GAIN_DEFAULT      62

/* Vendor normal-mode gain table. The V4L2 control value is an index. */
static const u16 sc132gs_again_lut[] = {
	0x0320, 0x0321, 0x0321, 0x0322, 0x0323, 0x0324, 0x0324, 0x0325,
	0x0326, 0x0327, 0x0328, 0x0329, 0x0329, 0x032a, 0x032b, 0x032c,
	0x032d, 0x032e, 0x032f, 0x0330, 0x0331, 0x0332, 0x0334, 0x0335,
	0x0336, 0x0337, 0x0338, 0x0339, 0x2320, 0x2321, 0x2322, 0x2323,
	0x2323, 0x2324, 0x2325, 0x2326, 0x2327, 0x2327, 0x2328, 0x2329,
	0x232a, 0x232b, 0x232c, 0x232d, 0x232e, 0x232f, 0x2330, 0x2331,
	0x2332, 0x2333, 0x2334, 0x2335, 0x2336, 0x2338, 0x2339, 0x233a,
	0x233b, 0x233d, 0x233e, 0x233f, 0x2720, 0x2721, 0x2722, 0x2723,
	0x2723, 0x2724, 0x2725, 0x2726, 0x2727, 0x2727, 0x2728, 0x2729,
	0x272a, 0x272b, 0x272c, 0x272d, 0x272e, 0x272f, 0x2730, 0x2731,
	0x2732, 0x2733, 0x2734, 0x2735, 0x2736, 0x2738, 0x2739, 0x273a,
	0x273b, 0x273d, 0x273e, 0x273f, 0x2f20, 0x2f21, 0x2f22, 0x2f23,
	0x2f23, 0x2f24, 0x2f25, 0x2f26, 0x2f27, 0x2f27, 0x2f28, 0x2f29,
	0x2f2a, 0x2f2b, 0x2f2c, 0x2f2d, 0x2f2e, 0x2f2f, 0x2f30, 0x2f31,
	0x2f32, 0x2f33, 0x2f34, 0x2f35, 0x2f36, 0x2f38, 0x2f39, 0x2f3a,
	0x2f3b, 0x2f3d, 0x2f3e, 0x2f3f, 0x3f20, 0x3f21, 0x3f22, 0x3f23,
	0x3f23,
};

static unsigned long link_freq_hz = SC132GS_LINK_FREQ_DEFAULT;
module_param(link_freq_hz, ulong, 0444);
MODULE_PARM_DESC(link_freq_hz,
		 "CSI-2 DDR clock frequency in Hz (half the per-lane bit rate)");

static bool force_external_trigger;
module_param_named(external_trigger, force_external_trigger, bool, 0444);
MODULE_PARM_DESC(external_trigger,
		 "Put every SC132GS instance in external FSYNC slave mode");

static s64 sc132gs_link_freq_menu[] = { SC132GS_LINK_FREQ_DEFAULT };

struct sc132gs_reg {
	u16 address;
	u8 value;
};

/* Public D-Robotics first-probe table; stream-on is intentionally separate. */
static const struct sc132gs_reg sc132gs_1088x1280_regs[] = {
	{0x0103, 0x01}, {0x0100, 0x00}, {0x36e9, 0x80}, {0x36f9, 0x80},
	{0x3018, 0x12}, {0x3019, 0x0e}, {0x301a, 0xb4}, {0x301f, 0x45},
	{0x3032, 0x60}, {0x3038, 0x44}, {0x3200, 0x00}, {0x3201, 0x02},
	{0x3202, 0x00}, {0x3203, 0x02}, {0x3204, 0x04}, {0x3205, 0x55},
	{0x3206, 0x05}, {0x3207, 0x15}, {0x3208, 0x04}, {0x3209, 0x40},
	{0x320a, 0x05}, {0x320b, 0x00}, {0x3210, 0x00}, {0x3211, 0x0a},
	{0x3212, 0x00}, {0x3213, 0x0c}, {0x320c, 0x02}, {0x320d, 0xee},
	{0x320e, 0x05}, {0x320f, 0x78}, {0x3250, 0xcc}, {0x3251, 0x02},
	{0x3252, 0x05}, {0x3253, 0x73}, {0x3254, 0x05}, {0x3255, 0x3b},
	{0x3306, 0x78}, {0x330a, 0x00}, {0x330b, 0xc8}, {0x330f, 0x24},
	{0x3314, 0x80}, {0x3315, 0x40}, {0x3317, 0xf0}, {0x331f, 0x12},
	{0x3364, 0x00}, {0x3385, 0x41}, {0x3387, 0x41}, {0x3389, 0x09},
	{0x33ab, 0x00}, {0x33ac, 0x00}, {0x33b1, 0x03}, {0x33b2, 0x12},
	{0x33f8, 0x02}, {0x33fa, 0x01}, {0x3409, 0x08}, {0x34f0, 0xc0},
	{0x34f1, 0x20}, {0x34f2, 0x03}, {0x3622, 0xf5}, {0x3630, 0x5c},
	{0x3631, 0x80}, {0x3632, 0xc8}, {0x3633, 0x32}, {0x3638, 0x2a},
	{0x3639, 0x07}, {0x363b, 0x48}, {0x363c, 0x83}, {0x363d, 0x10},
	{0x36ea, 0x37}, {0x36eb, 0x04}, {0x36ec, 0x03}, {0x36ed, 0x24},
	{0x36fa, 0x2b}, {0x36fb, 0x0b}, {0x36fc, 0x01}, {0x36fd, 0x34},
	{0x3900, 0x11}, {0x3901, 0x05}, {0x3902, 0xc5}, {0x3904, 0x04},
	{0x3908, 0x91}, {0x391e, 0x00}, {0x3e00, 0x00}, {0x3e01, 0x34},
	{0x3e02, 0x80}, {0x3e06, 0x00}, {0x3e07, 0x80}, {0x3e08, 0x27},
	{0x3e09, 0x22}, {0x3e0e, 0xd2}, {0x3e14, 0xb0}, {0x3e1e, 0x7c},
	{0x3e26, 0x20}, {0x4418, 0x38}, {0x4503, 0x10}, {0x4837, 0x0f},
	{0x5000, 0x0e}, {0x540c, 0x51}, {0x550f, 0x38}, {0x5780, 0x67},
	{0x5784, 0x10}, {0x5785, 0x06}, {0x5787, 0x02}, {0x5788, 0x00},
	{0x5789, 0x00}, {0x578a, 0x02}, {0x578b, 0x00}, {0x578c, 0x00},
	{0x5790, 0x00}, {0x5791, 0x00}, {0x5792, 0x00}, {0x5793, 0x00},
	{0x5794, 0x00}, {0x5795, 0x00}, {0x5799, 0x04}, {0x3e01, 0x32},
	{0x3e02, 0x80}, {0x36e9, 0x24},
	{0x36f9, 0x50},
};

/*
 * SmartSens SC132GS single-frame slave trigger settings from the public
 * D-Robotics driver.  Apply after the common mode table and before stream-on.
 * The trigger source owns FSYNC; this driver must not drive that line.
 */
static const struct sc132gs_reg sc132gs_external_trigger_regs[] = {
	{0x3222, 0x02}, {0x3223, 0x48}, {0x3226, 0x08}, {0x3227, 0x08},
	{0x3217, 0x00}, {0x3218, 0x00}, {0x322b, 0x0b},
	{0x320e, 0x3f}, {0x320f, 0xff}, {0x3225, 0x04}, {0x300a, 0x62},
};

/* On this RUBIK Pi setup the standard slave table emitted every second
 * 60 Hz FSYNC pulse.  Keeping the trigger pad settings while restoring VTS
 * and 0x3222 produced one frame per pulse and stopped when FSYNC stopped.
 */
static const struct sc132gs_reg sc132gs_trigger_60fps_regs[] = {
	{0x320e, 0x05}, {0x320f, 0x78}, {0x3222, 0x00},
};

struct sc132gs {
	struct device *dev;
	struct regmap *regmap;
	struct clk *xclk;
	struct gpio_desc *reset_gpio;
	struct v4l2_subdev sd;
	struct media_pad pad;
	struct v4l2_ctrl_handler ctrls;
	struct v4l2_ctrl *exposure;
	struct v4l2_ctrl *analogue_gain;
	struct mutex lock;
	bool streaming;
	bool external_trigger;
	bool hardware_initialized;
};

static int sc132gs_write_exposure(struct sc132gs *sensor, unsigned int lines)
{
	int ret;

	ret = regmap_write(sensor->regmap, SC132GS_REG_EXPOSURE_H,
			   (lines >> 12) & 0x0f);
	if (ret)
		return ret;
	ret = regmap_write(sensor->regmap, SC132GS_REG_EXPOSURE_H + 1,
			   (lines >> 4) & 0xff);
	if (ret)
		return ret;
	return regmap_write(sensor->regmap, SC132GS_REG_EXPOSURE_H + 2,
			    (lines & 0x0f) << 4);
}

static int sc132gs_write_analogue_gain(struct sc132gs *sensor,
				      unsigned int index)
{
	u16 code = sc132gs_again_lut[index];
	int ret;

	ret = regmap_write(sensor->regmap, SC132GS_REG_ANALOGUE_GAIN,
			   code >> 8);
	if (ret)
		return ret;
	return regmap_write(sensor->regmap, SC132GS_REG_ANALOGUE_GAIN + 1,
			    code & 0xff);
}

static int sc132gs_set_ctrl(struct v4l2_ctrl *ctrl)
{
	struct sc132gs *sensor = container_of(ctrl->handler, struct sc132gs,
						 ctrls);

	/* The current mode table is restored before every stream-on. */
	if (!sensor->streaming)
		return 0;
	switch (ctrl->id) {
	case V4L2_CID_EXPOSURE:
		return sc132gs_write_exposure(sensor, ctrl->val);
	case V4L2_CID_ANALOGUE_GAIN:
		return sc132gs_write_analogue_gain(sensor, ctrl->val);
	default:
		return -EINVAL;
	}
}

static const struct v4l2_ctrl_ops sc132gs_ctrl_ops = {
	.s_ctrl = sc132gs_set_ctrl,
};

static inline struct sc132gs *to_sc132gs(struct v4l2_subdev *sd)
{
	return container_of(sd, struct sc132gs, sd);
}

static int sc132gs_power_on(struct sc132gs *sensor)
{
	bool reset_sensor = sensor->reset_gpio &&
		(!sensor->external_trigger || !sensor->hardware_initialized);
	int ret;

	if (reset_sensor) {
		gpiod_set_value_cansleep(sensor->reset_gpio, 1);
		usleep_range(5000, 6000);
	}
	if (sensor->xclk) {
		ret = clk_set_rate(sensor->xclk, SC132GS_XCLK_HZ);
		if (ret)
			return ret;
		ret = clk_prepare_enable(sensor->xclk);
		if (ret)
			return ret;
	}
	if (reset_sensor)
		gpiod_set_value_cansleep(sensor->reset_gpio, 0);
	usleep_range(10000, 12000);
	sensor->hardware_initialized = true;
	return 0;
}

static void sc132gs_power_off(struct sc132gs *sensor)
{
	/* Keep a trigger-mode sensor out of reset between stream sessions. */
	if (sensor->reset_gpio && !sensor->external_trigger)
		gpiod_set_value_cansleep(sensor->reset_gpio, 1);
	if (sensor->xclk)
		clk_disable_unprepare(sensor->xclk);
}

static int sc132gs_write_regs(struct sc132gs *sensor,
			      const struct sc132gs_reg *regs,
			      size_t count)
{
	unsigned int i;
	int ret;

	for (i = 0; i < count; ++i) {
		ret = regmap_write(sensor->regmap, regs[i].address, regs[i].value);
		if (ret)
			return ret;
	}
	return 0;
}

static int sc132gs_write_mode(struct sc132gs *sensor)
{
	int ret;

	ret = sc132gs_write_regs(sensor, sc132gs_1088x1280_regs,
				 ARRAY_SIZE(sc132gs_1088x1280_regs));
	if (ret || !sensor->external_trigger)
		return ret;

	return sc132gs_write_regs(sensor, sc132gs_external_trigger_regs,
				  ARRAY_SIZE(sc132gs_external_trigger_regs));
}

static ssize_t trigger_60fps_store(struct device *dev,
				   struct device_attribute *attr,
				   const char *buf, size_t count)
{
	struct v4l2_subdev *sd = i2c_get_clientdata(to_i2c_client(dev));
	struct sc132gs *sensor = to_sc132gs(sd);
	unsigned int value;
	unsigned int i;
	int ret = 0;

	if (!sysfs_streq(buf, "1"))
		return -EINVAL;

	mutex_lock(&sensor->lock);
	if (!sensor->streaming || !sensor->external_trigger) {
		ret = -EBUSY;
		goto unlock;
	}
	ret = sc132gs_write_regs(sensor, sc132gs_trigger_60fps_regs,
				 ARRAY_SIZE(sc132gs_trigger_60fps_regs));
	if (ret)
		goto unlock;
	for (i = 0; i < ARRAY_SIZE(sc132gs_trigger_60fps_regs); ++i) {
		ret = regmap_read(sensor->regmap,
				  sc132gs_trigger_60fps_regs[i].address, &value);
		if (ret)
			goto unlock;
		if (value != sc132gs_trigger_60fps_regs[i].value) {
			ret = -EIO;
			goto unlock;
		}
	}
	dev_info(dev, "60 Hz FSYNC overrides applied after stream-on\n");
unlock:
	mutex_unlock(&sensor->lock);
	return ret ? ret : count;
}
static DEVICE_ATTR_WO(trigger_60fps);

static int sc132gs_verify_mode(struct sc132gs *sensor)
{
	static const struct sc132gs_reg common_expected[] = {
		{0x3018, 0x12}, {0x3019, 0x0e}, {0x301a, 0xb4},
		{0x301f, 0x45}, {0x320c, 0x02}, {0x320d, 0xee},
		{0x36e9, 0x24}, {0x36f9, 0x50}, {0x3e01, 0x32},
		{0x3e02, 0x80}, {0x4837, 0x0f},
	};
	static const struct sc132gs_reg free_run_expected[] = {
		{0x320e, 0x05}, {0x320f, 0x78},
	};
	const struct sc132gs_reg *mode_expected;
	size_t mode_count;
	unsigned int value;
	unsigned int i;
	int ret;

	for (i = 0; i < ARRAY_SIZE(common_expected); ++i) {
		ret = regmap_read(sensor->regmap, common_expected[i].address, &value);
		if (ret)
			return ret;
		if (value != common_expected[i].value) {
			dev_err(sensor->dev,
				"mode verify failed: reg 0x%04x expected 0x%02x got 0x%02x\n",
				common_expected[i].address,
				common_expected[i].value, value);
			return -EIO;
		}
	}

	if (sensor->external_trigger) {
		mode_expected = sc132gs_external_trigger_regs;
		mode_count = ARRAY_SIZE(sc132gs_external_trigger_regs);
	} else {
		mode_expected = free_run_expected;
		mode_count = ARRAY_SIZE(free_run_expected);
	}

	for (i = 0; i < mode_count; ++i) {
		ret = regmap_read(sensor->regmap, mode_expected[i].address, &value);
		if (ret)
			return ret;
		/*
		 * SC132GS register 0x300a contains an FSYNC pad status bit at
		 * bit 3.  The two connectors may therefore read 0x62 or 0x6a
		 * depending on the current input level even though the writable
		 * configuration bits were accepted.  Ignore only that status bit.
		 */
		if (mode_expected[i].address == 0x300a &&
		    !((value ^ mode_expected[i].value) & ~0x08))
			continue;
		if (value != mode_expected[i].value) {
			dev_err(sensor->dev,
				"mode verify failed: reg 0x%04x expected 0x%02x got 0x%02x\n",
				mode_expected[i].address,
				mode_expected[i].value, value);
			return -EIO;
		}
	}

	dev_info(sensor->dev,
		 "mode read-back verified (%zu critical registers, %s)\n",
		 ARRAY_SIZE(common_expected) + mode_count,
		 sensor->external_trigger ? "external-trigger slave" : "free-run");
	return 0;
}

static int sc132gs_s_stream(struct v4l2_subdev *sd, int enable)
{
	struct sc132gs *sensor = to_sc132gs(sd);
	unsigned int mode;
	int ret = 0;

	mutex_lock(&sensor->lock);
	dev_info(sensor->dev, "stream request: %s (current=%s)\n",
		 enable ? "on" : "off", sensor->streaming ? "on" : "off");
	if (sensor->streaming == !!enable)
		goto unlock;

	if (enable) {
		ret = sc132gs_power_on(sensor);
		if (ret)
			goto unlock;
		ret = sc132gs_write_mode(sensor);
		if (!ret) {
			dev_info(sensor->dev, "mode table written (%zu registers, %s)\n",
				 ARRAY_SIZE(sc132gs_1088x1280_regs) +
				 (sensor->external_trigger ?
				  ARRAY_SIZE(sc132gs_external_trigger_regs) : 0),
				 sensor->external_trigger ?
				 "external-trigger slave" : "free-run");
			ret = sc132gs_verify_mode(sensor);
		}
		if (!ret)
			ret = sc132gs_write_exposure(sensor,
					     sensor->exposure->val);
		if (!ret)
			ret = sc132gs_write_analogue_gain(sensor,
						  sensor->analogue_gain->val);
		if (!ret) {
			ret = regmap_write(sensor->regmap, SC132GS_REG_CTRL_MODE,
					   SC132GS_MODE_STREAMING);
		}
		if (ret) {
			dev_err(sensor->dev, "stream-on programming failed: %d\n", ret);
			sc132gs_power_off(sensor);
			goto unlock;
		}
		ret = regmap_read(sensor->regmap, SC132GS_REG_CTRL_MODE, &mode);
		if (ret || mode != SC132GS_MODE_STREAMING) {
			dev_err(sensor->dev,
				"stream register read-back failed: ret=%d value=0x%02x\n",
				ret, ret ? 0 : mode);
			if (!ret)
				ret = -EIO;
			sc132gs_power_off(sensor);
			goto unlock;
		}
		dev_info(sensor->dev, "stream-on confirmed: reg 0x0100=0x%02x\n",
			 mode);
	} else {
		ret = regmap_write(sensor->regmap, SC132GS_REG_CTRL_MODE,
				   SC132GS_MODE_STANDBY);
		if (ret)
			dev_err(sensor->dev, "stream-off programming failed: %d\n", ret);
		sc132gs_power_off(sensor);
	}
	sensor->streaming = !!enable;

unlock:
	mutex_unlock(&sensor->lock);
	return ret;
}

static int sc132gs_enum_mbus_code(struct v4l2_subdev *sd,
				  struct v4l2_subdev_state *state,
				  struct v4l2_subdev_mbus_code_enum *code)
{
	if (code->index)
		return -EINVAL;
	code->code = MEDIA_BUS_FMT_SRGGB10_1X10;
	return 0;
}

static int sc132gs_enum_frame_size(struct v4l2_subdev *sd,
				   struct v4l2_subdev_state *state,
				   struct v4l2_subdev_frame_size_enum *fse)
{
	if (fse->index || fse->code != MEDIA_BUS_FMT_SRGGB10_1X10)
		return -EINVAL;
	fse->min_width = fse->max_width = SC132GS_WIDTH;
	fse->min_height = fse->max_height = SC132GS_HEIGHT;
	return 0;
}

static void sc132gs_fill_format(struct v4l2_mbus_framefmt *fmt)
{
	fmt->width = SC132GS_WIDTH;
	fmt->height = SC132GS_HEIGHT;
	fmt->code = MEDIA_BUS_FMT_SRGGB10_1X10;
	fmt->field = V4L2_FIELD_NONE;
	fmt->colorspace = V4L2_COLORSPACE_RAW;
	fmt->ycbcr_enc = V4L2_YCBCR_ENC_DEFAULT;
	fmt->quantization = V4L2_QUANTIZATION_FULL_RANGE;
	fmt->xfer_func = V4L2_XFER_FUNC_NONE;
}

static int sc132gs_get_fmt(struct v4l2_subdev *sd,
			   struct v4l2_subdev_state *state,
			   struct v4l2_subdev_format *format)
{
	sc132gs_fill_format(&format->format);
	return 0;
}

static int sc132gs_set_fmt(struct v4l2_subdev *sd,
			   struct v4l2_subdev_state *state,
			   struct v4l2_subdev_format *format)
{
	sc132gs_fill_format(&format->format);
	return 0;
}

static const struct v4l2_subdev_video_ops sc132gs_video_ops = {
	.s_stream = sc132gs_s_stream,
};

static const struct v4l2_subdev_pad_ops sc132gs_pad_ops = {
	.enum_mbus_code = sc132gs_enum_mbus_code,
	.enum_frame_size = sc132gs_enum_frame_size,
	.get_fmt = sc132gs_get_fmt,
	.set_fmt = sc132gs_set_fmt,
};

static const struct v4l2_subdev_ops sc132gs_subdev_ops = {
	.video = &sc132gs_video_ops,
	.pad = &sc132gs_pad_ops,
};

static const struct regmap_config sc132gs_regmap_config = {
	.reg_bits = 16,
	.val_bits = 8,
	.cache_type = REGCACHE_NONE,
};

static int sc132gs_identify(struct sc132gs *sensor)
{
	unsigned int high, low;
	int ret;

	ret = regmap_read(sensor->regmap, SC132GS_REG_CHIP_ID, &high);
	if (ret)
		return ret;
	ret = regmap_read(sensor->regmap, SC132GS_REG_CHIP_ID + 1, &low);
	if (ret)
		return ret;
	if (((high << 8) | low) != SC132GS_CHIP_ID) {
		dev_err(sensor->dev, "unexpected chip id 0x%04x\n",
			(high << 8) | low);
		return -ENODEV;
	}
	dev_info(sensor->dev, "SC132GS chip id 0x%04x\n", SC132GS_CHIP_ID);
	return 0;
}

static int sc132gs_probe(struct i2c_client *client)
{
	struct device *dev = &client->dev;
	struct sc132gs *sensor;
	struct v4l2_ctrl *ctrl;
	int ret;

	sensor = devm_kzalloc(dev, sizeof(*sensor), GFP_KERNEL);
	if (!sensor)
		return -ENOMEM;
	sensor->dev = dev;
	mutex_init(&sensor->lock);
	sensor->external_trigger = force_external_trigger ||
		of_property_read_bool(dev->of_node, "smartsens,external-trigger");

	sensor->regmap = devm_regmap_init_i2c(client, &sc132gs_regmap_config);
	if (IS_ERR(sensor->regmap))
		return dev_err_probe(dev, PTR_ERR(sensor->regmap), "regmap init failed\n");
	sensor->xclk = devm_clk_get_optional(dev, "xclk");
	if (IS_ERR(sensor->xclk))
		return dev_err_probe(dev, PTR_ERR(sensor->xclk), "xclk lookup failed\n");
	/*
	 * Hardware A/B testing on GS130WI established that RUBIK Pi
	 * CAMERA_GPIO (TLMM57/58) is RESET: asserting it makes the sensor stop
	 * acknowledging CCI immediately.  Always own it as reset.  The common
	 * FSYNC source is deliberately owned outside this sensor driver so one
	 * GPIO operation can change both trigger lines atomically.
	 */
	sensor->reset_gpio = devm_gpiod_get_optional(dev, "reset",
						    GPIOD_OUT_HIGH);
	if (IS_ERR(sensor->reset_gpio))
		return dev_err_probe(dev, PTR_ERR(sensor->reset_gpio),
				     "reset gpio failed\n");

	ret = sc132gs_power_on(sensor);
	if (ret)
		return dev_err_probe(dev, ret, "power-on failed\n");
	ret = sc132gs_identify(sensor);
	sc132gs_power_off(sensor);
	if (ret)
		return dev_err_probe(dev, ret, "sensor identification failed\n");

	v4l2_i2c_subdev_init(&sensor->sd, client, &sc132gs_subdev_ops);
	sensor->sd.flags |= V4L2_SUBDEV_FL_HAS_DEVNODE;
	sensor->sd.entity.function = MEDIA_ENT_F_CAM_SENSOR;
	sensor->pad.flags = MEDIA_PAD_FL_SOURCE;
	ret = media_entity_pads_init(&sensor->sd.entity, 1, &sensor->pad);
	if (ret)
		return ret;

	sc132gs_link_freq_menu[0] = link_freq_hz;
	v4l2_ctrl_handler_init(&sensor->ctrls, 4);
	sensor->ctrls.lock = &sensor->lock;
	ctrl = v4l2_ctrl_new_int_menu(&sensor->ctrls, NULL,
				      V4L2_CID_LINK_FREQ,
				      ARRAY_SIZE(sc132gs_link_freq_menu) - 1, 0,
				      sc132gs_link_freq_menu);
	if (ctrl)
		ctrl->flags |= V4L2_CTRL_FLAG_READ_ONLY;
	sensor->exposure = v4l2_ctrl_new_std(&sensor->ctrls,
					     &sc132gs_ctrl_ops,
					     V4L2_CID_EXPOSURE, 8,
					     SC132GS_EXPOSURE_MAX, 1,
					     SC132GS_EXPOSURE_DEFAULT);
	sensor->analogue_gain = v4l2_ctrl_new_std(&sensor->ctrls,
						  &sc132gs_ctrl_ops,
						  V4L2_CID_ANALOGUE_GAIN,
						  0,
						  ARRAY_SIZE(sc132gs_again_lut) - 1,
						  1, SC132GS_GAIN_DEFAULT);
	ctrl = v4l2_ctrl_new_std(&sensor->ctrls, NULL, V4L2_CID_PIXEL_RATE,
				 SC132GS_PIXEL_RATE, SC132GS_PIXEL_RATE, 1,
				 SC132GS_PIXEL_RATE);
	if (ctrl)
		ctrl->flags |= V4L2_CTRL_FLAG_READ_ONLY;
	if (sensor->ctrls.error) {
		ret = sensor->ctrls.error;
		goto free_entity;
	}
	sensor->sd.ctrl_handler = &sensor->ctrls;

	ret = v4l2_async_register_subdev_sensor(&sensor->sd);
	if (ret)
		goto free_ctrls;
	ret = device_create_file(dev, &dev_attr_trigger_60fps);
	if (ret) {
		v4l2_async_unregister_subdev(&sensor->sd);
		goto free_ctrls;
	}

	dev_info(dev,
		 "registered fixed 1088x1280 RAW10 mode, link frequency %lu Hz, %s\n",
		 link_freq_hz,
		 sensor->external_trigger ? "external-trigger slave" : "free-run");
	return 0;

free_ctrls:
	v4l2_ctrl_handler_free(&sensor->ctrls);
free_entity:
	media_entity_cleanup(&sensor->sd.entity);
	return ret;
}

static void sc132gs_remove(struct i2c_client *client)
{
	struct v4l2_subdev *sd = i2c_get_clientdata(client);
	struct sc132gs *sensor = to_sc132gs(sd);

	device_remove_file(&client->dev, &dev_attr_trigger_60fps);
	v4l2_async_unregister_subdev(sd);
	v4l2_ctrl_handler_free(&sensor->ctrls);
	media_entity_cleanup(&sd->entity);
	mutex_destroy(&sensor->lock);
}

static const struct of_device_id sc132gs_of_match[] = {
	{ .compatible = "smartsens,sc132gs" },
	{ }
};
MODULE_DEVICE_TABLE(of, sc132gs_of_match);

static struct i2c_driver sc132gs_i2c_driver = {
	.driver = {
		.name = "sc132gs",
		.of_match_table = sc132gs_of_match,
	},
	.probe = sc132gs_probe,
	.remove = sc132gs_remove,
};
module_i2c_driver(sc132gs_i2c_driver);

MODULE_DESCRIPTION("Minimal SmartSens SC132GS V4L2 sensor driver");
MODULE_LICENSE("GPL");
