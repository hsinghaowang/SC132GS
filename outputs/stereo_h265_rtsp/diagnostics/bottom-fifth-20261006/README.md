# Lower-fifth texture investigation, 2026-10-06

The user's new screenshot and current software-decoded RTSP both retain
fine texture near the lower fifth after the initial RGGB reconstruction.
Earlier reconstructed RAW already contains it, so the issue is not confined
to VLC or H.265. Independent RAW captures at fixed exposure=2176 and gain
indices 0/54 preserve the HDR sensor mode and show greater noise at gain54.
They were captured sequentially; they are not synchronized with the saved
RTSP image and do not establish correspondence for an intermittent defect.

`gain-ab.json` records temporal variation over three RAW frames for each
gain/camera. `phase-noise.json` records phase-dependent temporal variation
after bilinear reconstruction: about 1.0 versus 1.5–2.0 grayscale levels.
This provides a mechanism for residual lattice-like noise, but is not a
complete characterization of sensor fixed-pattern noise or HDR calibration.

The attempted spatial denoise reduced the lower-area 2x2 intensity spread
from6 to3, but failed to remove the fixed boundary. It has been removed from
production. Historical `same-raw-denoise.png` is not the final correction.

## Final sensor correction

The HDR FSYNC profile incorrectly reused linear-mode `0x3225=0x04`. Keep
`0x3222=0x32`, HDR mode and all dimensions, but restore `0x3225=0x00`, the
sensor-reset default. Single-register A/B fixes the lower-band pattern in
both cameras. `hdr-gate-before-after.png` shows crops reconstructed from
separate RAW captures with identical gain/exposure and without spatial
denoise. Last128-row same-CFA high-pass residual drops from~23/~27.5 to~6/~6
RAW10 levels; actual post-reboot captures give~5.9/~5.5. This diagnostic
includes real scene texture, so it is not a complete sensor-noise calibration.

Turning `0x3222` back to vendor `0x30` or experimental `0x31` also cleans the
picture but becomes free-running: a20-Hz trigger still produces30FPS. This
is rejected as a stereo solution. `0x3225=0x00` preserves trigger-following:
20Hz gives~20FPS. Lowering trigger rate alone to20/25Hz with faulty0x04 did
not improve the pattern. Delay/default-row-start tests also did not fix it.

Height registers read1280 on both sensors, ROI end=0x0517, offset12; bottom
RAW data updates every frame (~85% changed bytes). Both CSID color-bar RAW
test patterns have consistent phases across all1280 rows. Synthetic solid
gray through the hardware H.265 encoder/software decoder has zero variance
over the entire frame. These reject simple missing-row/stale-buffer and
constant-input encoder hypotheses, not every possible transport failure.

Driver correction installed/rebooted: srcversionDA7B3C0F0D0C59EB9501BA3,
SHA2561b5ed91882d10b71f12b29bfb61c4dfa29d3181fee5b08bb1c9acefc95716e8d.
Both sensors read0x3225=0 after restart; STREAMON verification includes it.
Backup module: `/home/ubuntu/sc132gs-bottom-fifth-20261006/sc132gs-before-gate-fix.ko`.

Final verification:600 continuous pairs at30.08FPS, maximum receiver timestamp
difference314us;292 distinct2176x1280 software-decoded frames at30.46FPS,
encoded PTS cadence~30FPS. HDR=1, AE has no reported error/brightness limit.
Production contains Bayer reconstruction but no spatial/temporal denoise.
See `capture-gate-final.txt`, `gate-final-raw.json`, `decode-gate-final.json`,
`after-gate-fix-stream.png` and `board-gate-final-status.txt`.

Exposure control caveat: under faulty0x04,3e31/32 control200/808/2176 did not
change brightness, while3e00..02 did. Its physical meaning in the corrected
HDR trigger mode is not established by this image-artifact correction.
