GS130WI IMU 200-Hz FIFO acquisition - RUBIK Pi 3
==============================================

2026-10-15 update: optional --fsync mode is implemented and board-tested.
See FSYNC.zh-TW.md for configuration, CSV field semantics, evidence, and limits.
Public API now supports C++17. Historical results below describe the default
FSYNC-off profile unless explicitly stated otherwise. --fsync does not publish
validated host sample times or camera trigger IDs.

Current verification (2026-10-05, Asia/Taipei)
------------------------------------------
Built and executed on kernel 6.8.0-1084-qcom with GCC 13.3, C++20,
-Wall -Wextra -Wpedantic -Werror. No kernel or Device Tree was changed.
Sensor: ICM-42688-P, address 0x68, WHO_AM_I 0x47, CCI1 master 0.
Current runtime endpoint: /dev/i2c-18. The adapter number can change.
Bus remains configured at 100 kHz. Accel +/-4 g; gyro +/-500 deg/s.

30-second capture:
  6066 valid packets; 434 timestamp counter wraps.
  Nominal sensor time intervals: 4,999,467 to 5,000,533 ns.
  Rate derived from sensor time: 200 Hz.
  Rate observed using host read times: 202.213 Hz in this run.
  Maximum observed FIFO backlog: 352 bytes.
  FIFO full/lost-packet checks and timestamp continuity checks passed.
  All saved writable configuration registers read back equal after stop.

120-ms deliberate host stall:
  1212 valid packets over the six-second capture, maximum backlog 656 bytes.
  No detected timestamp discontinuity or overflow; configuration restored.
800-ms deliberate host stall:
  Explicit fifo_overflow error, nonzero program exit; power/ranges/FIFO readback
  confirmed restored. Data after overflow are not published as a valid stream.

INT1 wired verification (same date, after user wiring confirmation):
  Yellow -> physical PIN13/GPIO24/INT1; red -> physical PIN14/GND.
  Black/INT2 remains disconnected. Color mapping is for this supplied cable.
  TLMM GPIO chip /dev/gpiochip4, offset 24, kernel CLOCK_MONOTONIC event time.
  30-second IRQ capture: 6072 valid packets, 435 sensor counter wraps,
  observed host rate 202.390 Hz, maximum FIFO backlog 192 bytes.
  Six-second IRQ capture with 120-ms stall: 1215 valid packets,
  maximum backlog 544 bytes. Neither run detected overflow/discontinuity.
  Configuration restoration passed, with independent power/FIFO/INT readback.

First wired run received one IRQ then timed out: FIFO refilled above watermark
before the latched interrupt was cleared. IRQ mode now enables FIFO_WM_GT_TH
so the watermark condition is re-evaluated on subsequent ODRs. Both corrected
runs used IRQ waiting only, with no automatic polling fallback.
An earlier run with wires disconnected correctly returned interrupt_timeout.
Real IMU interrupt delivery is now verified. Host/sample clock mapping,
electrical edge timing, camera synchronization, deliberate motion response and
calibration remain unverified.
The two observed clock rates are not assumed equal: do not use the nominal
sensor elapsed time as an absolute host timestamp without calibration.

Run on the board
----------------
Sources and executable are at /home/ubuntu/gs130wi-imu.

  cd ~/gs130wi-imu
  sudo ./build/gs130wi-imu --seconds 30 > imu.csv 2> imu-summary.json

CSV has separate sensor_elapsed_ns, host_read_begin_ns, host_read_end_ns and
host_interrupt_ns fields. sensor_elapsed_ns starts at zero for the first sample
of each run. It is derived from the actual FIFO counter, not a host sleep loop.
It is NOT an epoch time or a verified camera exposure timestamp.
host_interrupt_ns is blank in polling mode. In IRQ mode it is a batch-level
notification time repeated on that batch's CSV rows; it is NOT the individual
sample timestamp. Header/validity/raw timestamp are
preserved. SI-style values here are g and deg/s, not m/s^2 and rad/s.
Ctrl+C stops capture and attempts restoration. SIGKILL/power loss cannot run
destructors. If those occur, inspect the sensor configuration before restarting;
the tool refuses to take over an already active sensor/FIFO.

  cmake -S . -B build
  cmake --build build -j2

Critical transport details
--------------------------
CCI accepts at most 12 read bytes per message. ICM FIFO packet type 3 is 16
bytes. FIFO_RESUME_PARTIAL_RD is enabled. The first read addresses FIFO_DATA;
consecutive read-only transfers continue that FIFO stream. A non-FIFO register
access invalidates the cached pointer and the next FIFO read addresses it again.
This mode was verified on this ICM-42688-P/CCI path using packet headers,
timestamps, all-axis data and hundreds of timestamp wraps.

Re-addressing the FIFO for every 12-byte transfer was too slow on this board
and caused overflow. --readdress-fifo retains that mode for diagnostics only.
--benchmark measures register-read transaction duration without enabling IMU.
One process owns the IMU. The cooperative flock protects other copies of this
tool; external i2ctransfer commands do not honor it. Do not use another IMU
register client during a capture. Shared camera transactions to address 0x32
do not select the IMU register pointer, but compete for bus time; combined
camera/IMU load was not tested in the original run. The 2026-10-15 update
includes a bounded 60-second capture alongside live camera/RTSP; see FSYNC.zh-TW.md.

Timestamp details
-----------------
TMST_DELTA_EN=0, TMST_FSYNC_EN=0, TMST_RES=0, RTC_MODE=0.
Each type-3 FIFO packet must report an ODR timestamp (header bits 3:2 = 10).
The 16-bit counter is unwrapped using unsigned consecutive differences.
For the internal-clock mode, DS-000347 rev1.6 section 12.7 requires a 32/30
scale factor, despite the TMST_RES setting being described as 1 microsecond.
sensor_elapsed_ns = accumulated_raw_ticks * 32000 / 30.
Out-of-range intervals cause timestamp_discontinuity rather than an invented
timestamp. FIFO overflow stops the acquisition rather than concealing loss.
Nominal resolution is not a measurement of absolute accuracy or oscillator
drift. host_sample_time_validated remains false in the summary.

INT1 wiring - verified installation
----------------------------------
Shut down the board and remove power before connecting wires.
Use connector PIN NUMBERS, not cable colors:

  GS130WI PIN1 / INT1 (yellow on this cable) -> RUBIK physical PIN13 / GPIO24
  GS130WI PIN3 / GND (red on this cable)     -> RUBIK physical PIN14 / GND
  GS130WI PIN2 / INT2 (black on this cable)  -> leave disconnected/insulated

The physical pin number 13 is not GPIO line offset 13. The verified line offset
is 24 on the current TLMM chip /dev/gpiochip4 (label f100000.pinctrl). Recheck
the chip label after reboot. Follow the official PIN1 orientation drawing and
verify ground continuity while unpowered. Do not generalize this cable's
confirmed wire colors to other assemblies. Confirm INT1 logic voltage is compatible with
the RUBIK 3.3-V header before connecting the signal. Do not connect a power
pin; do not add a strong external pull-up to the RUBIK level-shifted header.
The EXT/LPWM switch selects INT2 routing; it does not select INT1.

After wiring and restoring power:

  cd ~/gs130wi-imu
  sudo ./build/gs130wi-imu --gpiochip /dev/gpiochip4 --line 24 --seconds 30 \
    > imu-irq.csv 2> imu-irq-summary.json

IRQ profile: active-high push-pull latched INT1; four-packet FIFO watermark;
FIFO_WM_GT_TH enabled to retrigger while backlog stays above the watermark;
GPIO-v2 rising-edge notification with the kernel CLOCK_MONOTONIC event time.
The optional interrupt interface waits for notifications; the sensor reader
drains FIFO and then clears the latched source. A missing interrupt times out
as a structured error rather than silently falling back to polling.
Exact IRQ-to-sample association and sensor-to-host offset/slope fitting are the
next validation step. Capturing the GPIO timestamp alone does not prove sample
time accuracy, nor compensate sensor/filter/interrupt latency.

Design
------
icm42688.hpp: C++20 public API, move-only sensor, PIMPL, structured ErrorCode.
Required register transport injected by reference; optional interrupt role by
pointer. Dependencies must outlive the reader. Synchronous Results are separate
from interrupt notification. Single-owner/thread usage; no hidden callbacks.
Linux I2C/GPIO headers, fd ownership and platform details are private to CLI.
Reader stop/destructor restore registers; stop explicitly verifies readback.

References
----------
https://developer.d-robotics.cc/accessories_stereo_camera_doc/en/stereo_camera_gs130wi/hardware
https://product.tdk.com.cn/system/files/dam/doc/product/sensor/mortion-inertial/imu/data_sheet/ds-000347-icm-42688-p-v1.6.pdf
https://raw.githubusercontent.com/rubikpi-ai/documentation/main/docs-en/docs/rubik-pi-3-user-manual/1.1.0/images/image-88.jpg
