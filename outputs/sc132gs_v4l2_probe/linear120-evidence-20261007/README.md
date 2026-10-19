Latest follow-up: [120 FPS profile audit and hardware results](profile-audit/README.zh-TW.md). A new candidate subsequently achieved dual-eye 120 FPS in free-run; external-trigger 120 FPS remains unverified. The measurements below concern the original deployed 60 FPS table.

# Linear 120 FPS verification — 2026-10-07

Result: **120 FPS not achieved with the currently deployed Linear sensor mode.**
This test does not prove the sensor or the two-lane hardware cannot support a properly configured 120 FPS mode.

## Board and method

RUBIK Pi 3, dual SC132GS; runtime identity discovered through the media graph:
CAM0 `sc132gs 18-0032`, CAM1 `sc132gs 16-0030`.
Both eyes have WDR disabled, 1088 × 1280 RAW10, and two lanes confirmed by
sensor register readback (`3018=32`, `3019=0c`). Driver link-frequency parameter
is 600 MHz; this is the configured receiver value, not a physical lane-rate measurement.

Stopped the RTSP owner, retained the deployed sensor table/PLL, started the existing
GPIO FSYNC generator at each requested rate, and applied the deployed
`trigger_60fps` overrides after both streams were armed. These overrides retain
HTS `02ee`, VTS `0578`, `3222=00`, `3225=04`.
Exposure was shortened to 500 rows (about 5.95 ms according to the existing Linear
row-time model), gain index 41, to avoid the existing 15.8 ms exposure being the
reason a requested 8.33 ms frame interval failed.

`linear-rate-check.cpp` is a diagnostic copy of the existing V4L2 MMAP checker.
It performs no Bayer conversion, encoding, RTSP, or display work. It discards
120 startup frames and records 600 completed frames per eye. Every dequeued
buffer is checked for V4L2 error flags and the expected 1,740,800-byte payload.
FPS is computed from V4L2 receiver timestamps, not the requested generator rate.
CSV files preserve every measured sequence, timestamp, and sparse payload hash.
Diagnostic compiled on the board with C++20, O2, Wall/Wextra/Werror.

## Measurements

| Requested generator rate | CAM0 measured FPS | CAM1 measured FPS | Sequence gap events per eye | Aligned timestamp p95 | Result against requested FPS |
|---|---:|---:|---|---:|---|
| 60 Hz baseline | 60.0000 | 59.9995 | 0 / 0 | 291 us | PASS |
| 120 Hz first run | 60.0007 | 59.9999 | 0 / 0 | 8,472 us | FAIL |
| 90 Hz control | 59.9952 | 60.0004 | 0 / 0 | 290 us | FAIL |
| 120 Hz repeat | 59.9996 | 60.0005 | 0 / 0 | 233 us | FAIL |

All four runs produced 600 distinct sparse payload hashes per eye. This checks
payload variation; it does not establish optical scene fidelity. First-run 120 Hz
median timestamp difference was 8,332 us; repeat was 224 us. Higher requested
trigger frequency did not produce a stable 120 FPS stereo operating point.

Sequence continuity refers to completed V4L2 buffers. It does **not** prove that
every external trigger produced a frame. Generator Hz is a software request;
no oscilloscope measurement of electrical pulses or exposure start was made.
The checker's process exit code checks timestamp alignment only: the repeat's
exit 0 is **not** a 120 FPS pass. The table above judges measured FPS separately.

## Interpretation and next prerequisite

The current Linear readout configuration remains near 60 FPS even with 90/120 Hz
requested triggers. Because this test bypassed image conversion and streaming,
those downstream stages do not explain the measured ceiling in this experiment.
The evidence points to the current sensor readout/trigger configuration; it does
not identify one specific limiting register or establish the actual electrical
trigger cadence.

Before another 120 FPS verification, obtain a complete SC132GS/GS130WI two-lane
Linear 120 FPS sensor profile, including input clock, PLL/pixel clock, HTS/VTS,
exposure limits, MIPI rate/timing and external-trigger settings. More lanes alone
will not change the retained sensor readout timing. No speculative PLL table was
written and no production driver, Device Tree, or RTSP rate limit was changed.

## Restoration

Restored the original transient `sc132gs-hdr-rtsp` service environment:
Linear 60 FPS, brightness target 40, automatic exposure enabled.
Readback confirms Linear, approximately 60 FPS, no AE error, no brightness limit.
Windows RTSP/TCP received 483 H.265 access units over approximately eight seconds,
measured 60.36 FPS (`restored-rtsp.txt`). Board-side software H.265 decoding reached
EOS and produced actual JPEG frames (`restored-frame-00.jpg`,
`restored-decode.log`). This is recovery/image evidence, not a measurement of
Windows display FPS or end-to-end latency.

Raw measurements: `rate60/`, `rate120/`, `followup/rate90/`,
`followup/rate120/`. Readback snapshots, kernel logs, restoration logs and the
reproducible test scripts are included in this directory.