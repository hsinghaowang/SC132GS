/***************************************************************************
 * COPYRIGHT NOTICE
 * Copyright 2023 Horizon Robotics.
 * All rights reserved.
 ***************************************************************************/
#define pr_fmt(fmt)             "[sc132gs]:" fmt

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <assert.h>
#include <getopt.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <linux/i2c-dev.h>
#include "hb_i2c.h"
#include "hb_cam_utility.h"
#include "inc/sc132gs_setting.h"
#include "inc/sensor_effect_common.h"
#include "hb_camera_data_config.h"

#define MCLK (24000000)

//#define AE_DBG


#define SC1320GS_PROGRAM_GAIN	(0x3e08)
#define SC132GS_DIGITAL_GAIN	(0x3e06)
#define SC132GS_EXP_LINE		(0x3e00)
#define SC132GS_DOL2_SHORT_EXP_LINE		(0x3e04)

/*store sensor_info extra_mode*/
uint32_t extra_mode = 0;

// turning data init
int sc132gs_linear_data_init_896x896(sensor_info_t *sensor_info)
{
	int ret = RET_OK;
	uint32_t  open_cnt = 0;
	sensor_turning_data_t turning_data;
	uint32_t *stream_on = turning_data.stream_ctrl.stream_on;
	uint32_t *stream_off = turning_data.stream_ctrl.stream_off;

	memset(&turning_data, 0, sizeof(sensor_turning_data_t));

	// common data
	turning_data.bus_num = sensor_info->bus_num;
	turning_data.bus_type = sensor_info->bus_type;
	turning_data.port = sensor_info->port;
	turning_data.reg_width = sensor_info->reg_width;
	turning_data.mode = sensor_info->sensor_mode;
	turning_data.sensor_addr = sensor_info->sensor_addr;
	strncpy(turning_data.sensor_name, sensor_info->sensor_name,
		sizeof(turning_data.sensor_name));

	// turning sensor_data
	// lines_per_second = fps * vts, vts = {16‘h320e,16’h320f} = 1400
	// If trigger is enabled, the configuration before trigger will still be used.
	turning_data.sensor_data.lines_per_second = 42000;
	// form customer, exposure time max = 10ms
	turning_data.sensor_data.exposure_time_max = 420;

	turning_data.sensor_data.active_width = 896;
	turning_data.sensor_data.active_height = 896;
	turning_data.sensor_data.analog_gain_max = 154;
	turning_data.sensor_data.digital_gain_max = 159;   //159
	turning_data.sensor_data.exposure_time_min = 8;
	// No setting is required in linear mode
	turning_data.sensor_data.exposure_time_long_max = 4000;

	// raw10
	sensor_data_bayer_fill(&turning_data.sensor_data, 10, (uint32_t)BAYER_START_B, (uint32_t)BAYER_PATTERN_RGGB);
	sensor_data_bits_fill(&turning_data.sensor_data, 12);

	turning_data.stream_ctrl.data_length = 1;
	if(sizeof(turning_data.stream_ctrl.stream_on) >= sizeof(sc132gs_stream_on_setting)) {
		memcpy(stream_on, sc132gs_stream_on_setting, sizeof(sc132gs_stream_on_setting));
	} else {
		vin_err("Number of registers on stream over 10\n");
		return -RET_ERROR;
	}
	if(sizeof(turning_data.stream_ctrl.stream_off) >= sizeof(sc132gs_stream_off_setting)) {
		memcpy(stream_off, sc132gs_stream_off_setting, sizeof(sc132gs_stream_off_setting));
	} else {
		vin_err("Number of registers on stream over 10\n");
		return -RET_ERROR;
	}

	turning_data.normal.again_lut = malloc(256*sizeof(uint32_t));
	if (turning_data.normal.again_lut != NULL) {
		memset(turning_data.normal.again_lut, 0xff, 256*sizeof(uint32_t));
		memcpy(turning_data.normal.again_lut, sc132gs_gain_lut,
			sizeof(sc132gs_gain_lut));
		for (open_cnt =0; open_cnt <
			sizeof(sc132gs_gain_lut)/sizeof(uint32_t); open_cnt++) {
				// DOFFSET(&turning_data.normal.again_lut[open_cnt], 2);
		}
	}

	turning_data.normal.dgain_lut = malloc(256*sizeof(uint32_t));
	if (turning_data.normal.dgain_lut != NULL) {
		memset(turning_data.normal.dgain_lut, 0xff, 256*sizeof(uint32_t));
		memcpy(turning_data.normal.dgain_lut, sc132gs_dgain_lut,
			sizeof(sc132gs_dgain_lut));
		for (open_cnt =0; open_cnt <
			sizeof(sc132gs_dgain_lut)/sizeof(uint32_t); open_cnt++) {
				// DOFFSET(&turning_data.normal.dgain_lut[open_cnt], 2);
		}
	}

	ret = ioctl(sensor_info->sen_devfd, SENSOR_TURNING_PARAM, &turning_data);
	if (turning_data.normal.again_lut) {
		free(turning_data.normal.again_lut);
		turning_data.normal.again_lut = NULL;
	}
	if (turning_data.normal.dgain_lut) {
		free(turning_data.normal.dgain_lut);
		turning_data.normal.dgain_lut = NULL;
	}
	if (ret < 0) {
		vin_err("sensor_%d ioctl fail %d\n", ret);
		return -RET_ERROR;
	}

	return ret;
}

// turning data init
int sc132gs_linear_data_init_1088x1280(sensor_info_t *sensor_info)
{
	int ret = RET_OK;
	uint32_t  open_cnt = 0;
	sensor_turning_data_t turning_data;
	uint32_t *stream_on = turning_data.stream_ctrl.stream_on;
	uint32_t *stream_off = turning_data.stream_ctrl.stream_off;

	memset(&turning_data, 0, sizeof(sensor_turning_data_t));

	// common data
	turning_data.bus_num = sensor_info->bus_num;
	turning_data.bus_type = sensor_info->bus_type;
	turning_data.port = sensor_info->port;
	turning_data.reg_width = sensor_info->reg_width;
	turning_data.mode = sensor_info->sensor_mode;
	if (sensor_info->sensor_mode == SLAVE_M)
		turning_data.mode = NORMAL_M;
	turning_data.sensor_addr = sensor_info->sensor_addr;
	strncpy(turning_data.sensor_name, sensor_info->sensor_name,
		sizeof(turning_data.sensor_name));

	// turning sensor_data
	// lines_per_second = fps * vts, vts = {16‘h320e,16’h320f} = 1400
	// If trigger is enabled, the configuration before trigger will still be used.
	turning_data.sensor_data.lines_per_second = 84000;
	// form customer, exposure time max = 10ms
	turning_data.sensor_data.exposure_time_max = 2560;

	turning_data.sensor_data.active_width = 1088;
	turning_data.sensor_data.active_height = 1280;
	turning_data.sensor_data.analog_gain_max = 128;		//154
	turning_data.sensor_data.digital_gain_max = 0;   //159
	turning_data.sensor_data.exposure_time_min = 1;
	// No setting is required in linear mode
	turning_data.sensor_data.exposure_time_long_max = 4000;
	turning_data.sensor_data.analog_gain_init = 62;
	turning_data.sensor_data.digital_gain_init = 0;
	turning_data.sensor_data.exposure_time_init = 840;
	turning_data.sensor_data.delta_time = 2;

	// raw10
	sensor_data_bayer_fill(&turning_data.sensor_data, 10, (uint32_t)BAYER_START_B, (uint32_t)BAYER_PATTERN_RGGB);
	sensor_data_bits_fill(&turning_data.sensor_data, 12);

	turning_data.stream_ctrl.data_length = 1;
	if(sizeof(turning_data.stream_ctrl.stream_on) >= sizeof(sc132gs_stream_on_setting)) {
		memcpy(stream_on, sc132gs_stream_on_setting, sizeof(sc132gs_stream_on_setting));
	} else {
		vin_err("Number of registers on stream over 10\n");
		return -RET_ERROR;
	}
	if(sizeof(turning_data.stream_ctrl.stream_off) >= sizeof(sc132gs_stream_off_setting)) {
		memcpy(stream_off, sc132gs_stream_off_setting, sizeof(sc132gs_stream_off_setting));
	} else {
		vin_err("Number of registers on stream over 10\n");
		return -RET_ERROR;
	}

	turning_data.normal.again_lut = malloc(256*sizeof(uint32_t));
	if (turning_data.normal.again_lut != NULL) {
		memset(turning_data.normal.again_lut, 0xff, 256*sizeof(uint32_t));
		memcpy(turning_data.normal.again_lut, sc132gs_gain_lut,
			sizeof(sc132gs_gain_lut));
		for (open_cnt =0; open_cnt <
			sizeof(sc132gs_gain_lut)/sizeof(uint32_t); open_cnt++) {
				// DOFFSET(&turning_data.normal.again_lut[open_cnt], 2);
		}
	}

	turning_data.normal.dgain_lut = malloc(256*sizeof(uint32_t));
	if (turning_data.normal.dgain_lut != NULL) {
		memset(turning_data.normal.dgain_lut, 0xff, 256*sizeof(uint32_t));
		memcpy(turning_data.normal.dgain_lut, sc132gs_dgain_lut,
			sizeof(sc132gs_dgain_lut));
		for (open_cnt =0; open_cnt <
			sizeof(sc132gs_dgain_lut)/sizeof(uint32_t); open_cnt++) {
				// DOFFSET(&turning_data.normal.dgain_lut[open_cnt], 2);
		}
	}

	ret = ioctl(sensor_info->sen_devfd, SENSOR_TURNING_PARAM, &turning_data);
	if (turning_data.normal.again_lut) {
		free(turning_data.normal.again_lut);
		turning_data.normal.again_lut = NULL;
	}
	if (turning_data.normal.dgain_lut) {
		free(turning_data.normal.dgain_lut);
		turning_data.normal.dgain_lut = NULL;
	}
	if (ret < 0) {
		vin_err("sensor_%d ioctl fail %d\n", ret);
		return -RET_ERROR;
	}

	return ret;
}


int sc132gs_dol2_data_init_896x896(sensor_info_t *sensor_info)
{
	int ret = RET_OK;
	uint32_t  open_cnt = 0;
	sensor_turning_data_t turning_data;
	uint32_t *stream_on = turning_data.stream_ctrl.stream_on;
	uint32_t *stream_off = turning_data.stream_ctrl.stream_off;

	memset(&turning_data, 0, sizeof(sensor_turning_data_t));

	// common data
	turning_data.bus_num = sensor_info->bus_num;
	turning_data.bus_type = sensor_info->bus_type;
	turning_data.port = sensor_info->port;
	turning_data.reg_width = sensor_info->reg_width;
	turning_data.mode = sensor_info->sensor_mode;
	turning_data.sensor_addr = sensor_info->sensor_addr;
	strncpy(turning_data.sensor_name, sensor_info->sensor_name,
		sizeof(turning_data.sensor_name));

	// turning sensor_data
	turning_data.sensor_data.turning_type = 6;
	turning_data.sensor_data.lines_per_second = 60240;
	turning_data.sensor_data.exposure_time_max = 968;

	turning_data.sensor_data.active_width = 1088;
	turning_data.sensor_data.active_height = 1280;
	// turning_data.sensor_data.gain_max = 128 * 8192;
	turning_data.sensor_data.analog_gain_max = 205*8192;
	turning_data.sensor_data.digital_gain_max = 159*8192;
	turning_data.sensor_data.exposure_time_min = 1;
	turning_data.sensor_data.exposure_time_long_max = 2176;
	// turning_data.sensor_data.conversion = 1;

	// turning normal
	// // // short frame
	// turning_data.dol2.s_line = SC1330T_DOL2_SHORT_EXP_LINE;
	// turning_data.dol2.s_line_length = 2;
	// // long frame
	// turning_data.dol2.m_line = S1330T_EXP_LINE;
	// turning_data.dol2.m_line_length = 2;

		// raw10
		sensor_data_bayer_fill(&turning_data.sensor_data, 10, (uint32_t)BAYER_START_R, (uint32_t)BAYER_PATTERN_RGGB);
		sensor_data_bits_fill(&turning_data.sensor_data, 12);


	turning_data.dol2.line_p[0].ratio = 1 << 8;
	turning_data.dol2.line_p[0].offset = 0;
	turning_data.dol2.line_p[0].max = 66;
	turning_data.dol2.line_p[1].ratio = 1 << 8;
	turning_data.dol2.line_p[1].offset = 0;
	turning_data.dol2.line_p[1].max = 2176;

#if 0
	turning_data.dol2.again_control_num = 1;
	turning_data.dol2.again_control[0] = SC132GS_PROGRAM_GAIN;
	turning_data.dol2.again_control_length[0] = 2;
	turning_data.dol2.dgain_control_num = 1;
	turning_data.dol2.dgain_control_length[0] = 2;
	turning_data.dol2.dgain_control[0] = SC132GS_DIGITAL_GAIN;
#endif

	turning_data.stream_ctrl.data_length = 1;
	if(sizeof(turning_data.stream_ctrl.stream_on) >= sizeof(sc132gs_stream_on_setting)) {
		memcpy(stream_on, sc132gs_stream_on_setting, sizeof(sc132gs_stream_on_setting));
	} else {
		vin_err("Number of registers on stream over 10\n");
		return -RET_ERROR;
	}
	if(sizeof(turning_data.stream_ctrl.stream_on) >= sizeof(sc132gs_stream_off_setting)) {
		memcpy(stream_off, sc132gs_stream_off_setting, sizeof(sc132gs_stream_off_setting));
	} else {
		vin_err("Number of registers on stream over 10\n");
		return -RET_ERROR;
	}

	turning_data.dol2.again_lut = malloc(256*sizeof(uint32_t));
	if (turning_data.dol2.again_lut != NULL) {
		memset(turning_data.dol2.again_lut, 0xff, 256*sizeof(uint32_t));
		memcpy(turning_data.dol2.again_lut, sc132gs_gain_lut,
			sizeof(sc132gs_gain_lut));
		for (open_cnt =0; open_cnt <
			sizeof(sc132gs_gain_lut)/sizeof(uint32_t); open_cnt++) {
				// DOFFSET(&turning_data.dol2.again_lut[open_cnt], 2);
		}
	}

	turning_data.dol2.dgain_lut = malloc(256*sizeof(uint32_t));
	if (turning_data.dol2.dgain_lut != NULL) {
		memset(turning_data.dol2.dgain_lut, 0xff, 256*sizeof(uint32_t));
		memcpy(turning_data.dol2.dgain_lut, sc132gs_dgain_lut,
			sizeof(sc132gs_dgain_lut));
		for (open_cnt =0; open_cnt <
			sizeof(sc132gs_dgain_lut)/sizeof(uint32_t); open_cnt++) {
				// DOFFSET(&turning_data.dol2.dgain_lut[open_cnt], 2);
		}
	}

	ret = ioctl(sensor_info->sen_devfd, SENSOR_TURNING_PARAM, &turning_data);
	if (turning_data.dol2.again_lut) {
		free(turning_data.dol2.again_lut);
		turning_data.dol2.again_lut = NULL;
	}
	if (turning_data.dol2.dgain_lut) {
		free(turning_data.dol2.dgain_lut);
		turning_data.dol2.dgain_lut = NULL;
	}
	if (ret < 0) {
		vin_err("sensor_%d ioctl fail %d\n", ret);
		return -RET_ERROR;
	}

	return ret;
}

int sc132gs_dol2_data_init_1088x1280(sensor_info_t *sensor_info)
{
	int ret = RET_OK;
	uint32_t  open_cnt = 0;
	sensor_turning_data_t turning_data;
	uint32_t *stream_on = turning_data.stream_ctrl.stream_on;
	uint32_t *stream_off = turning_data.stream_ctrl.stream_off;

	memset(&turning_data, 0, sizeof(sensor_turning_data_t));

	// common data
	turning_data.bus_num = sensor_info->bus_num;
	turning_data.bus_type = sensor_info->bus_type;
	turning_data.port = sensor_info->port;
	turning_data.reg_width = sensor_info->reg_width;
	turning_data.mode = sensor_info->sensor_mode;
	turning_data.sensor_addr = sensor_info->sensor_addr;
	strncpy(turning_data.sensor_name, sensor_info->sensor_name,
		sizeof(turning_data.sensor_name));

	// turning sensor_data
	turning_data.sensor_data.turning_type = 6;
	turning_data.sensor_data.lines_per_second = 135000;
	turning_data.sensor_data.exposure_time_max = 968;

	turning_data.sensor_data.active_width = 1088;
	turning_data.sensor_data.active_height = 1280;
	// turning_data.sensor_data.gain_max = 128 * 8192;
	turning_data.sensor_data.analog_gain_max = 205*8192;
	turning_data.sensor_data.digital_gain_max = 159*8192;
	turning_data.sensor_data.exposure_time_min = 1;
	turning_data.sensor_data.exposure_time_long_max = 2176;
	// turning_data.sensor_data.conversion = 1;

	// turning normal
	// // // short frame
	// turning_data.dol2.s_line = SC1330T_DOL2_SHORT_EXP_LINE;
	// turning_data.dol2.s_line_length = 2;
	// // long frame
	// turning_data.dol2.m_line = S1330T_EXP_LINE;
	// turning_data.dol2.m_line_length = 2;

	if(sensor_info->extra_mode == 1)
	{
		printf("%s sensor_info->extra_mode  == 1 \n" , __func__);
		turning_data.sensor_data.lines_per_second = 45000;
		turning_data.sensor_data.lines_per_second *= 4;
		turning_data.sensor_data.exposure_time_max *= 4;
		turning_data.sensor_data.exposure_time_min *= 1;
		turning_data.sensor_data.exposure_time_long_max *= 4;
		turning_data.sensor_data.exposure_time_init *= 4;
		turning_data.sensor_data.delta_time *= 4;
	}
	// raw10
	sensor_data_bayer_fill(&turning_data.sensor_data, 10, (uint32_t)BAYER_START_B, (uint32_t)BAYER_PATTERN_RGGB);
	sensor_data_bits_fill(&turning_data.sensor_data, 12);


	turning_data.dol2.line_p[0].ratio = 1 << 8;
	turning_data.dol2.line_p[0].offset = 0;
	turning_data.dol2.line_p[0].max = 66;
	turning_data.dol2.line_p[1].ratio = 1 << 8;
	turning_data.dol2.line_p[1].offset = 0;
	turning_data.dol2.line_p[1].max = 2176;

#if 0
	turning_data.dol2.again_control_num = 1;
	turning_data.dol2.again_control[0] = SC132GS_PROGRAM_GAIN;
	turning_data.dol2.again_control_length[0] = 2;
	turning_data.dol2.dgain_control_num = 1;
	turning_data.dol2.dgain_control_length[0] = 2;
	turning_data.dol2.dgain_control[0] = SC132GS_DIGITAL_GAIN;
#endif

	turning_data.stream_ctrl.data_length = 1;
	if(sizeof(turning_data.stream_ctrl.stream_on) >= sizeof(sc132gs_stream_on_setting)) {
		memcpy(stream_on, sc132gs_stream_on_setting, sizeof(sc132gs_stream_on_setting));
	} else {
		vin_err("Number of registers on stream over 10\n");
		return -RET_ERROR;
	}
	if(sizeof(turning_data.stream_ctrl.stream_on) >= sizeof(sc132gs_stream_off_setting)) {
		memcpy(stream_off, sc132gs_stream_off_setting, sizeof(sc132gs_stream_off_setting));
	} else {
		vin_err("Number of registers on stream over 10\n");
		return -RET_ERROR;
	}

	turning_data.dol2.again_lut = malloc(256*sizeof(uint32_t));
	if (turning_data.dol2.again_lut != NULL) {
		memset(turning_data.dol2.again_lut, 0xff, 256*sizeof(uint32_t));
		memcpy(turning_data.dol2.again_lut, sc132gs_gain_lut,
			sizeof(sc132gs_gain_lut));
		for (open_cnt =0; open_cnt <
			sizeof(sc132gs_gain_lut)/sizeof(uint32_t); open_cnt++) {
				// DOFFSET(&turning_data.dol2.again_lut[open_cnt], 2);
		}
	}

	turning_data.dol2.dgain_lut = malloc(256*sizeof(uint32_t));
	if (turning_data.dol2.dgain_lut != NULL) {
		memset(turning_data.dol2.dgain_lut, 0xff, 256*sizeof(uint32_t));
		memcpy(turning_data.dol2.dgain_lut, sc132gs_dgain_lut,
			sizeof(sc132gs_dgain_lut));
		for (open_cnt =0; open_cnt <
			sizeof(sc132gs_dgain_lut)/sizeof(uint32_t); open_cnt++) {
				// DOFFSET(&turning_data.dol2.dgain_lut[open_cnt], 2);
		}
	}

	ret = ioctl(sensor_info->sen_devfd, SENSOR_TURNING_PARAM, &turning_data);
	if (turning_data.dol2.again_lut) {
		free(turning_data.dol2.again_lut);
		turning_data.dol2.again_lut = NULL;
	}
	if (turning_data.dol2.dgain_lut) {
		free(turning_data.dol2.dgain_lut);
		turning_data.dol2.dgain_lut = NULL;
	}
	if (ret < 0) {
		vin_err("sensor_%d ioctl fail %d\n", ret);
		return -RET_ERROR;
	}

	return ret;
}


int sensor_poweroff(sensor_info_t *sensor_info)
{
	int gpio, ret = RET_OK;

	if(sensor_info->gpio_num > 0) {
		for(gpio = 0; gpio < sensor_info->gpio_num; gpio++) {
			if(sensor_info->gpio_pin[gpio] != -1) {
				ret = vin_power_ctrl(sensor_info->gpio_pin[gpio],
									sensor_info->gpio_level[gpio]);
				if(ret < 0) {
					vin_err("vin_power_ctrl fail\n");
					return -1;
				}
			}
		}
	}

	return ret;
}

int sensor_poweron(sensor_info_t *sensor_info)
{
	int gpio, ret = RET_OK;
	if(sensor_info->gpio_num > 0) {
		for(gpio = 0; gpio < sensor_info->gpio_num; gpio++) {
			if(sensor_info->gpio_pin[gpio] != -1) {
				ret = vin_power_ctrl(sensor_info->gpio_pin[gpio],
						sensor_info->gpio_level[gpio]);
				usleep(1 * 100 * 1000);  //100ms
				ret |= vin_power_ctrl(sensor_info->gpio_pin[gpio],
						1 - sensor_info->gpio_level[gpio]);
				if(ret < 0) {
					vin_err("vin_power_ctrl fail\n");
					return -HB_CAM_SENSOR_POWERON_FAIL;
				}
				usleep(100*1000);  //100ms
			}
		}
	}

	return ret;
}

static int sensor_configure(sensor_info_t *sensor_info, const uint32_t *setting, int setting_size)
{
	int ret = RET_OK;

	vin_info("sensor %s enable fps: %d, setting_size = %d, bus_num = %d, sensor_addr = 0x%0x\n",
		sensor_info->sensor_name, sensor_info->fps, setting_size,
		sensor_info->bus_num, sensor_info->sensor_addr);

	return vin_write_array(sensor_info->bus_num, sensor_info->sensor_addr, 2, setting_size, setting);
}

int sensor_init(sensor_info_t *sensor_info)
{
	int ret = RET_OK;
	int setting_size = 0;

	extra_mode = sensor_info->extra_mode;

	ret = sensor_poweron(sensor_info);
	if (ret < 0) {
		vin_err("%d : sensor reset %s fail\n",
			   __LINE__, sensor_info->sensor_name);
		return ret;
	}

	if (sensor_info->width == 896 && sensor_info->height == 896) {
		switch(sensor_info->sensor_mode) {
		case NORMAL_M:	  // 1: normal
			vin_info("sc132gs in normal mode\n");
			setting_size = sizeof(sc132gs_linear_init_896x896_10fps_setting_master) / sizeof(uint32_t) / 2;
			ret = sensor_configure(sensor_info, sc132gs_linear_init_896x896_10fps_setting_master, setting_size);
			if (ret < 0) {
				vin_err("%d : init %s fail\n", __LINE__, sensor_info->sensor_name);
				return ret;
			}
			ret = sc132gs_linear_data_init_896x896(sensor_info);
			if (ret < 0) {
				vin_err("%d : linear data init %s fail\n", __LINE__, sensor_info->sensor_name);
				return ret;
			}
			break;
		case DOL2_M:  // 2: DOl2
			vin_info("sc132gs in dol2 mode\n");
			setting_size = sizeof(sc132gs_hdr_init_896x896_10fps_setting) / sizeof(uint32_t) / 2;
			ret = sensor_configure(sensor_info, sc132gs_hdr_init_896x896_10fps_setting, setting_size);
			if (ret < 0) {
				vin_err("%d : init %s fail\n", __LINE__, sensor_info->sensor_name);
				return ret;
			}
			ret = sc132gs_dol2_data_init_896x896(sensor_info);
			if (ret < 0) {
				vin_err("%d : dol2 data init %s fail\n", __LINE__, sensor_info->sensor_name);
				return ret;
			}
			break;
		case SLAVE_M:	  // 6: slave
			vin_info("sc132gs in slave mode\n");
			setting_size = sizeof(sc132gs_linear_init_896x896_10fps_setting_slave) / sizeof(uint32_t) / 2;
			ret = sensor_configure(sensor_info, sc132gs_linear_init_896x896_10fps_setting_slave, setting_size);
			if (ret < 0) {
				vin_err("%d : init %s fail\n", __LINE__, sensor_info->sensor_name);
				return ret;
			}
			ret = sc132gs_linear_data_init_896x896(sensor_info);
			if (ret < 0) {
				vin_err("%d : linear data init %s fail\n", __LINE__, sensor_info->sensor_name);
				return ret;
			}
			break;
		default:
			vin_err("not support mode %d\n", sensor_info->sensor_mode);
			ret = -RET_ERROR;
			break;
		}
	}else if (sensor_info->width == 1088 && sensor_info->height == 1280) {
		switch(sensor_info->sensor_mode) {
		case NORMAL_M:	  // 1: normal
			vin_info("sc132gs in normal mode , extra_mode = %d\n",sensor_info->extra_mode);
			if(sensor_info->extra_mode == 1)
			{
				vin_info("sc132gs in extra_mode mode\n");
				setting_size = sizeof(sc132gs_hdr_init_1088x1280_30fps_setting) / sizeof(uint32_t) / 2;
				ret = sensor_configure(sensor_info, sc132gs_hdr_init_1088x1280_30fps_setting, setting_size);
				if (ret < 0) {
					vin_err("%d : init %s fail\n", __LINE__, sensor_info->sensor_name);
					return ret;
				}
				ret = sc132gs_dol2_data_init_1088x1280(sensor_info);
				if (ret < 0) {
					vin_err("%d : extra_mode dol2 data init %s fail\n", __LINE__, sensor_info->sensor_name);
					return ret;
				}
				break;
			}
			else
			{
				vin_info("sc132gs in normal mode\n");
				setting_size = sizeof(sc132gs_linear_init_1088x1280_60fps_setting_master) / sizeof(uint32_t) / 2;
				ret = sensor_configure(sensor_info, sc132gs_linear_init_1088x1280_60fps_setting_master, setting_size);
				if (ret < 0) {
					vin_err("%d : init %s fail\n", __LINE__, sensor_info->sensor_name);
					return ret;
				}
				ret = sc132gs_linear_data_init_1088x1280(sensor_info);
				if (ret < 0) {
					vin_err("%d : linear data init %s fail\n", __LINE__, sensor_info->sensor_name);
					return ret;
				}
				break;
			}
		case SLAVE_M:	  // 6: slave
			vin_info("sc132gs in slave mode\n");
			setting_size = sizeof(sc132gs_linear_init_1088x1280_30fps_setting_slave) / sizeof(uint32_t) / 2;
			ret = sensor_configure(sensor_info, sc132gs_linear_init_1088x1280_30fps_setting_slave, setting_size);
			if (ret < 0) {
				vin_err("%d : init %s fail\n", __LINE__, sensor_info->sensor_name);
				return ret;
			}
			ret = sc132gs_linear_data_init_1088x1280(sensor_info);
			if (ret < 0) {
				vin_err("%d : linear data init %s fail\n", __LINE__, sensor_info->sensor_name);
				return ret;
			}
			break;
		default:
			vin_err("not support mode %d\n", sensor_info->sensor_mode);
			ret = -RET_ERROR;
			break;
		}
	}
	vin_info("sc132gs config success under %d mode\n\n", sensor_info->sensor_mode);

	return ret;
}
// start stream
int sensor_start(sensor_info_t *sensor_info)
{
	int ret = RET_OK;
	int setting_size = 0;

	switch(sensor_info->sensor_mode) {
	case NORMAL_M:
	case SLAVE_M:
		setting_size = sizeof(sc132gs_stream_on_setting)/sizeof(uint32_t)/2;
		vin_info(" start linear mode, sensor_name %s, setting_size = %d\n", sensor_info->sensor_name, setting_size);
		ret = vin_write_array(sensor_info->bus_num, sensor_info->sensor_addr, 2,
				setting_size, sc132gs_stream_on_setting);
		if(ret < 0) {
				vin_err("start %s fail\n", sensor_info->sensor_name);
				return ret;
		}
		break;
	case DOL2_M:
		setting_size = sizeof(sc132gs_stream_on_setting)/sizeof(uint32_t)/2;
		vin_info("start hdr mode, sensor_name %s, setting_size = %d\n", sensor_info->sensor_name, setting_size);
		ret = vin_write_array(sensor_info->bus_num, sensor_info->sensor_addr, 2,
				setting_size, sc132gs_stream_on_setting);
		if(ret < 0) {
				vin_err("start %s fail\n", sensor_info->sensor_name);
				return ret;
		}
		break;
	}

	return ret;
}

int sensor_stop(sensor_info_t *sensor_info)
{
	int ret = RET_OK;
	int setting_size = 0;

		setting_size =
				sizeof(sc132gs_stream_off_setting) / sizeof(uint32_t) / 2;
		vin_info("sensor stop sensor_name %s, setting_size = %d\n",
				sensor_info->sensor_name, setting_size);
		ret = vin_write_array(sensor_info->bus_num,
							 sensor_info->sensor_addr, 2,
							 setting_size, sc132gs_stream_off_setting);
		if (ret < 0)
		{
				vin_err("start %s fail\n", sensor_info->sensor_name);
				return ret;
		}

		return ret;
}

int sensor_deinit(sensor_info_t *sensor_info)
{
	int ret = RET_OK;

	ret = sensor_poweroff(sensor_info);
	if (ret < 0)
	{
		vin_err("%d : deinit %s fail\n",
			   __LINE__, sensor_info->sensor_name);
		return ret;
	}
	return ret;
}

static int sensor_aexp_gain_control(hal_control_info_t *info, uint32_t mode, uint32_t *again, uint32_t *dgain, uint32_t gain_num)
{
#ifdef AE_DBG
	printf("%s %s mode:%d gain_num:%d again[0]:%x, dgain[0]:%x\n", __FILE__, __FUNCTION__, mode, gain_num, again[0], dgain[0]);
#endif
	const uint16_t AGAIN_LOW = 0x3e08;
	const uint16_t AGAIN_HIGH = 0x3e09;
	const uint16_t DGAIN_LOW = 0x3e06;
	const uint16_t DGAIN_HIGH = 0x3e07;
	char ana_gain = 0, ana_fine_gain = 0;
	char dig_gain = 0, dig_fine_gain = 0;
	int again_index = 0, dgain_index = 0;
	if (mode == NORMAL_M || mode == DOL2_M) {
		if (again[0] >= sizeof(sc132gs_gain_lut)/sizeof(uint32_t))
			again_index = sizeof(sc132gs_gain_lut)/sizeof(uint32_t) - 1;
		else
			again_index = again[0];

		if (dgain[0] >= sizeof(sc132gs_dgain_lut)/sizeof(uint32_t))
			dgain_index = sizeof(sc132gs_dgain_lut)/sizeof(uint32_t) - 1;
		else
			dgain_index = dgain[0];

		ana_gain = (sc132gs_gain_lut[again_index] >> 8) & 0x000000FF;
		ana_fine_gain = sc132gs_gain_lut[again_index] & 0x000000FF;

		dig_gain = (sc132gs_dgain_lut[dgain_index] >> 8) & 0x000000FF;
		dig_fine_gain = sc132gs_dgain_lut[dgain_index] & 0x000000FF;
#ifdef AE_DBG
		printf("%s again(0x3e08/0x3e09):%x,%x; dgain(0x3e06x3e07):%x,%x\n",
				__FUNCTION__, ana_gain, ana_fine_gain, dig_gain, dig_fine_gain);
#endif
		vin_i2c_write8(info->bus_num, 16, info->sensor_addr, AGAIN_LOW, ana_gain);
		vin_i2c_write8(info->bus_num, 16, info->sensor_addr, AGAIN_HIGH, ana_fine_gain);
		vin_i2c_write8(info->bus_num, 16, info->sensor_addr, DGAIN_LOW, dig_gain);
		vin_i2c_write8(info->bus_num, 16, info->sensor_addr, DGAIN_HIGH, dig_fine_gain);
		if (mode == DOL2_M) {
			vin_i2c_write8(info->bus_num, 16, info->sensor_addr, 0x3e12, ana_gain);
			vin_i2c_write8(info->bus_num, 16, info->sensor_addr, 0x3e13, ana_fine_gain);
			vin_i2c_write8(info->bus_num, 16, info->sensor_addr, 0x3e10, dig_gain);
			vin_i2c_write8(info->bus_num, 16, info->sensor_addr, 0x3e11, dig_fine_gain);
		}

	} else	{
		vin_err(" unsupport mode %d\n", mode);
	}

	return 0;
}
static int sc132gs_ae_set(uint32_t bus, uint32_t addr, uint32_t line)
{
	const uint16_t EXP_LINE0 = 0x3e00;
	const uint16_t EXP_LINE1 = 0x3e01;
	const uint16_t EXP_LINE2 = 0x3e02;
	const uint16_t S_EXP_LINE0 = 0x3e04;
	const uint16_t S_EXP_LINE1 = 0x3e05;
	char temp0 = 0, temp1 = 0, temp2 = 0;

	uint32_t sline = line;
	/*
	 * NOTICE: trigger mode: sline = line(from isp)
	 * from customer, exposure time max is 10ms，sline = exposure_time_max = 420
	 */
	if (sline >= 2560)
		sline = 2560;

	temp0 = (sline & 0xF000) >> 12;
	temp1 = (sline & 0xFF0) >> 4;
	temp2 = (sline & 0x0F) << 4;
	vin_i2c_write8(bus, 16, addr, EXP_LINE0, temp0);
	vin_i2c_write8(bus, 16, addr, EXP_LINE1, temp1);
	vin_i2c_write8(bus, 16, addr, EXP_LINE2, temp2);

#ifdef AE_DBG
	printf("%s sline = %d, 0x3e00 = %x, 0x3e01 = %x, 0x3e02 = %x \n",
		__FUNCTION__, sline, temp0, temp1, temp2);
#endif

	return 0;
}

// 实现一个 1/16 行为曝光单位的方法

static int sc132gs_ae_set_extra_mode(uint32_t bus, uint32_t addr, uint32_t line)
{
	const uint16_t HDR_EXP_LINE0 = 0x3e31;
	const uint16_t HDR_EXP_LINE1 = 0x3e32;
	char temp0 = 0, temp1 = 0;

	uint32_t sline = line * 4;

	/*
	 * NOTICE: trigger mode: sline = line(from isp)
	 * from customer, exposure time max is 10ms，sline = exposure_time_max = 420
	 */
	// if (sline >= 2560)
	// 	sline = 2560;

	// HDR exposure only need 2 register to control
	temp0 = (sline & 0x0000FF00) >> 8;
	temp1 = (sline & 0x000000FF);
	vin_i2c_write8(bus, 16, addr, HDR_EXP_LINE0, temp0);
	vin_i2c_write8(bus, 16, addr, HDR_EXP_LINE1, temp1);

#ifdef AE_DBG
	printf("%s sline = %d, 0x3e31 = %x, 0x3e32 = %x \n",
		__FUNCTION__, sline, temp0, temp1);
#endif

	return 0;
}
#define SAMPLECNT 8

static int sensor_aexp_line_control(hal_control_info_t *info, uint32_t mode, uint32_t *line, uint32_t line_num)
{
#ifdef AE_DBG
	printf(" line mode %d, --line %d , line_num:%d \n", mode, line[0], line_num);
#endif
	uint32_t val;


	if (mode == NORMAL_M) {
		val = line[0];
		if(extra_mode == 1)
			sc132gs_ae_set_extra_mode(info->bus_num, info->sensor_addr, val);
		else
			sc132gs_ae_set(info->bus_num, info->sensor_addr, val);
	} else if (mode == DOL2_M) {
		//todo
	} else {
		vin_err(" unsupport mode %d\n", mode);
	}

	return 0;
}

static int sensor_userspace_control(uint32_t port, uint32_t *enable)
{
	vin_info("enable userspace gain control and line control\n");
	*enable = HAL_GAIN_CONTROL | HAL_LINE_CONTROL;
	return 0;
}

#ifdef CAMERA_FRAMEWORK_HBN
SENSOR_MODULE_F(sc132gs, CAM_MODULE_FLAG_A16D8);
sensor_module_t sc132gs = {
		.module = SENSOR_MNAME(sc132gs),
#else
sensor_module_t sc132gs = {
		.module = "sc132gs",
#endif
		.init = sensor_init,
		.start = sensor_start,
		.stop = sensor_stop,
		.deinit = sensor_deinit,
		.power_on = sensor_poweron,
		.power_off = sensor_poweroff,
		.aexp_gain_control = sensor_aexp_gain_control,
		.aexp_line_control = sensor_aexp_line_control,
		.userspace_control = sensor_userspace_control,
};
