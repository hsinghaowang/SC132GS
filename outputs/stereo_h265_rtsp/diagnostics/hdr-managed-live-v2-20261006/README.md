# Managed HDR preview, 2026-10-06

`comparison.png` and `highlight-comparison.png` compare real decoded RTSP
frames from Linear 60 FPS and the new HDR 30 FPS profile. Both modes requested
display brightness 40%; the sampled per-eye medians were 38/39% in Linear and
40/40% in HDR. Crops use x=650..1079, y=660..1059 within each horizontally
mirrored 1088x1280 eye. No extra brightness adjustment, denoising or sharpening
was applied to these comparison images after decoding.

`evidence.json` records all mode transitions, frozen sensor fields before
each RTSP capture, decoded-frame hashes, brightness targets/limits, control
rejections, loaded driver version and binary hash. Each RTSP image was obtained
after 30 decoded frames. `hdr-restart` is the historical label for a same-mode
request; it was a verified no-op. The reproduction script now calls this
`hdr-same-mode`.

`final-raw-evidence.json` records 12 complete distinct RAW10 frames per eye,
after 60 warm-up frames, with the final managed controls: TOTAL `5560`,
SECOND `0055`, coefficient `fe`, gain index 0, HDR mode `c3`, HDRC enable 1.
All frame hashes were verified again on Windows. `final-raw-analysis.json`
records 0% RAW samples >=1020 in both the lamp crop and whole frame, for
both eyes. RAW and RTSP were captured sequentially, not simultaneously.
This is evidence for this scene and profile, not a calibrated DR measurement.

Original final RAWs remain on the board at
`/home/ubuntu/sc132gs-hdr-final-raw-20261006/`. The earlier gain/ratio sweep is
in `../hdr-low-gain-20261006/`, and black-floor/TOTAL evidence is in
`../hdr-managed-raw-20261006/`. See
`../../../sc132gs_v4l2_probe/HDR_RATIO.md` for the driver/AE/display contract
and rollback paths.

`windows-rtsp-tcp.txt` verifies the Windows-to-board transport: 240 H.265
access units over eight seconds, approximately 29.93 FPS. This complements
the board-side decoder evidence; packet reception alone is not image proof.

Reproduction: copy `capture.py`, `capture-raw.py` and `hdr-strength-check.py`
together onto the board. With no other process owning the two cameras, run
as root with a fresh output directory:

```sh
python3 capture.py /home/ubuntu/new-hdr-live-check
python3 capture-raw.py /home/ubuntu/new-hdr-raw-check --current-only
```

The scripts stop/restart the stream and leave HDR with automatic target 40.
Copy original RAW files into the host's documented `tmp/hdrc-ratio` input
directory to rerun `analyze.py`; it verifies every recorded RAW frame hash.
The analysis scripts expect the current Windows project/font paths.
