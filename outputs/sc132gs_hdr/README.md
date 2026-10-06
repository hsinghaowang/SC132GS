# SC132GS single-frame HDR — 2026-10-06

The later mode-controller update supports both two-lane Linear 60 FPS and HDR
30 FPS with the same Device Tree. Use `sudo sc132gs-ctl set-mode linear` or
`sudo sc132gs-ctl set-mode hdr`; mode switches manage both eyes, AE and RTSP.
See [runtime mode switching](../sc132gs_v4l2_probe/MODE_SWITCH.md). The module
parameter selects only the initial mode; read actual runtime state with
`sc132gs-ctl mode` or `sudo sc132gs-ctl status`.

The two GS130WI sensors on RUBIK Pi 3 use the vendor 1088×1280 RAW10
30 FPS two-lane HDR register sequence. This enables sensor HDR; it does not
apply a contrast/gamma filter or alternate software exposures.

The RTSP capture path now reconstructs RGGB before converting to grayscale.
Treating the Bayer samples as monochrome had produced a regular 2×2 grid,
also present in historical linear-mode RAW. See the same-RAW comparison in
`../stereo_h265_rtsp/diagnostics/hdr-bottom-20261006/`. This userland correction
preserves the sensor HDR settings and 30-FPS capture mode.

## Changes

- Four active Device Tree endpoints changed from data-lanes `<0>` to `<0 1>`.
  The user confirmed that both cameras have the second differential pair wired.
  The current board identifiers uniquely matched combined-DTB entry 12; other
  board entries remain unchanged. The 64 MiB partition was backed up first.
- `sc132gs.c` adds immutable module parameter `hdr=1`. HDR requires two lanes
  and exposes read-only `wide_dynamic_range=1` through V4L2.
- The HDR sequence preserves `0x3220=0xc3`, `0x5001=0x01`, VTS=4500,
  and the vendor PLL/MIPI values. External triggering combines the previously
  validated pad settings with `0x3222=0x32`, preserving the HDR bits and adding
  the slave bit. HDR and FSYNC configuration are read back at STREAMON.
- HDR FSYNC uses `0x3225=0x00`, its sensor-reset default. Reusing the linear
  `0x04` creates a fixed lower-frame artifact. Both-camera RAW A/B confirmed
  the improvement, and a 20-Hz trigger-following test retained external
  control. Height registers remain 1280 and all rows update. Production
  output retains Bayer reconstruction and removes the attempted spatial
  denoise; the correction is in sensor configuration.
  Post-reboot verification: 600 contiguous pairs at30.08FPS, maximum
  receiver timestamp delta314us, 292 distinct decoded2176x1280 frames.
- Exposure follows the vendor `extra_mode` implementation: the control value
  multiplied by four is written to `0x3e31/0x3e32`. The driver uses a conservative
  control ceiling of 2176, based on the vendor long-exposure bound. These are
  compatibility control units: the datasheet's 1/16-line register encoding
  makes one HDR control step 1/4 nominal line. Physical duration in this trigger
  profile is not verified. HDRC ratio `0x5400` now follows the page-21 formula
  at every exposure update, grouped with `0x3e31/32`; see
  [ratio verification and RAW comparison](../sc132gs_v4l2_probe/HDR_RATIO.md).
  In the faulty trigger profile, changing this control from 200 to 2176 did
  not appreciably change scene brightness, while the legacy long-exposure
  registers did. A register write alone is not physical exposure validation.
- Linear 60-FPS timing overrides reject HDR with `EOPNOTSUPP`. The RTSP script
  requires `FPS=30` in this fixed HDR mode.
- AE queries the mode from both sensors, rejects mixed modes, uses the HDR
  driver exposure bound, and reports `hdr_enabled=1`. A positive
  `max-exposure-us` request returns `EOPNOTSUPP` in HDR until the physical timing
  conversion is characterized; `0` clears the optional limit.
- The linear-only 63 MHz pixel-rate control is omitted in HDR, since the HDR
  PLL changes. Link frequency remains separately available to CAMSS.

## Evidence

- Both chip IDs read `0x0132`; both boot with two-lane endpoints and HDR mode.
- Both sensor STREAMON operations verify the HDR register sequence.
- Each camera produced 5,222,400 bytes: three full 1,740,800-byte RAW10 frames.
  All six frame hashes differ. The raw previews show real scene content.
- Single-camera HDR capture measured approximately 29.99 FPS.
- External-trigger HDR capture: 120 paired frames, 30.13 FPS, maximum receiver
  timestamp difference 320 µs, no sequence gaps.
- Without FSYNC, one initial frame was delivered and further capture timed out.
- H.265 RTP-over-TCP probe: 148 access units over five seconds, 30.06 FPS.
- Software decoding produced 262 distinct RGB frames at 2176×1280; the
  saved composite visibly contains both camera images. Decoder wall throughput
  was 27.11 FPS; encoded timestamp cadence was 30 FPS.
- AE target 40% reached approximately 36%/40% on the two cameras with no control
  error and `brightness_limited=0`.
- Board C++ build and both existing RAW10/composition tests passed.

The receiver timestamp test does not establish electrical exposure skew. The
existing userspace FSYNC generator was reused for this HDR validation; migration
to a hardware clock source remains separate work. No calibrated dynamic-range
measurement or 100 dB claim is made. The board's `v4l2h265dec` produced green
output during validation, while `avdec_h265` decoded the same stream correctly;
the final image evidence therefore uses software decoding.

## Operating state

Persistent mode configuration:

```conf
# /etc/modprobe.d/sc132gs-external-trigger.conf
options sc132gs external_trigger=1 hdr=1
```

HDR DTB and driver are installed persistently. The current RTSP service is the
transient `sc132gs-hdr-rtsp.service`, which does not automatically return after
reboot. To start the existing stream after a reboot:

```bash
sudo modprobe qcom_camss
sudo /usr/local/sbin/configure-sc132gs-dual-pipeline
sudo env BIND=192.168.137.226 FPS=30 BRIGHTNESS=40 \
  bash /home/ubuntu/stereo-h265-rtsp/run-stereo-rtsp.sh
sudo sc132gs-ctl status
```

Use the current board IP if it changes. RTSP URL:
`rtsp://192.168.137.226:8554/stereo`.

## Backup and rollback

Board working directory: `/home/ubuntu/sc132gs-hdr-20261006/`.
It contains `dtb_a-before.img`, `combined-dtb-before.dtb`, the original driver,
original mode configuration, original AE sources, and original RTSP binary.

Stop the current HDR stream, then run:

```bash
sudo systemctl stop sc132gs-hdr-rtsp
sudo bash /home/ubuntu/sc132gs-hdr-20261006/rollback_hdr.sh
sudo reboot
```

Rollback restores the previous one-lane Device Tree, driver and module settings.
The new AE implementation also supports the old linear driver.

## Sources

- [SmartSens SC132GS product flyer](https://smartsens.oss-cn-beijing.aliyuncs.com/web/img/1741601896674553364.pdf): sensor single-frame HDR capability.
- [D-Robotics mode table](https://github.com/D-Robotics/x5-libcam-sensor/blob/ffc02ec611286e2a41423a05f6fce7c4897e1008/sc132gs/inc/sc132gs_setting.h): `sc132gs_hdr_init_1088x1280_30fps_setting`, with WIDTH defined.
- [D-Robotics exposure implementation](https://github.com/D-Robotics/x5-libcam-sensor/blob/main/sc132gs/sc132gs_utility.c): `sensor_init`, `sc132gs_ae_set_extra_mode`.
- [D-Robotics HDR receiver configuration](https://github.com/D-Robotics/x5-multimedia-samples/blob/95c090286c13bdc668ab4019493cd86617d8f103/vp_sensors/sc132gs/hdr_1088x1280_raw10_30fps_2lane.c): 2 lanes, RAW10, 30 FPS, one VC.
- [GS130WI hardware reference](https://developer.d-robotics.cc/accessories_stereo_camera_doc/en/stereo_camera_gs130wi/hardware): connector lane-1 pins 5/6.
