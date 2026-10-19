"""Bounded PC-side evidence collection for stereo/depth RTSP comparisons.

No sensor controls or services are modified. Each RTSP mount is decoded by a
separate process, so a missing/stalled mount cannot keep the collector alive.
Luma statistics describe decoded video code values, NOT linear sensor RAW or
metric depth. Geometry and transfer-function differences require separate review.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
from pathlib import Path
import subprocess
import sys
import time
import traceback


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def metadata(obj, names):
    result = {}
    for name in names:
        try:
            value = getattr(obj, name)
            result[name] = value if isinstance(value, (str, int, float, bool, type(None))) else str(value)
        except (AttributeError, ValueError, RuntimeError):
            result[name] = None
    return result


def native_luma(frame, np):
    """Read the coded Y plane with stride/endianness/bit alignment preserved."""
    fmt = frame.format.name
    if not (fmt.startswith("yuv") or fmt.startswith("yuva") or fmt.startswith("gray")
            or fmt in ("nv12", "nv21", "p010le", "p010be", "p016le", "p016be")):
        raise ValueError(f"Unsupported native luma pixel format: {fmt}")
    bits = int(frame.format.components[0].bits)
    if fmt.startswith("p010"):
        bits = 10
    if bits <= 8:
        dtype, step, shift = np.uint8, 1, 0
    elif bits <= 16:
        dtype, step = (">u2" if fmt.endswith("be") else "<u2"), 2
        shift = 6 if fmt.startswith("p010") else 0
    else:
        raise ValueError(f"Unsupported luma component width: {bits}")
    plane = frame.planes[0]
    # Ignore padding at the end of each row; do not reinterpret 10-bit as 8-bit.
    values = np.frombuffer(plane, dtype=dtype, count=frame.height * plane.line_size // step)
    values = values.reshape(frame.height, plane.line_size // step)[:, :frame.width]
    if shift:
        values = values >> shift
    return values, bits, {"dtype": str(dtype), "storage_shift": shift, "line_size": plane.line_size}


def luma_statistics(values, bits, np, color_range=None):
    # Full histogram for each ~1 Hz statistics sample. Gradients use adjacent
    # full-resolution pixels, with spatial subsampling only after differencing.
    maximum = (1 << bits) - 1
    hist = np.bincount(values.ravel().astype(np.int32), minlength=maximum + 1)
    sample = values[::4, ::4].astype(np.float32) / maximum
    grad_x = np.abs(values[::4, 1:].astype(np.float32) - values[::4, :-1].astype(np.float32))[:, ::4] / maximum
    grad_y = np.abs(values[1:, ::4].astype(np.float32) - values[:-1, ::4].astype(np.float32))[::4, :] / maximum
    gradients = np.concatenate((grad_x.ravel(), grad_y.ravel()))
    # These thresholds are explicitly coded levels. They are not a measurement
    # of RAW10 saturation, scene illumination, or a calibrated noise floor.
    result = {
        "coded_bits": bits,
        "full_code_normalization_denominator": maximum,
        "pixel_count": int(values.size),
        "histogram_code_counts": hist.tolist(),
        "code_min": int(values.min()), "code_max": int(values.max()),
        "sampled_mean_code_fraction": float(sample.mean()),
        "sampled_stddev_code_fraction": float(sample.std()),
        "sampled_percentiles_code_fraction": dict(zip(
            ("p01", "p05", "p50", "p95", "p99"),
            [float(v) for v in np.percentile(sample, [1, 5, 50, 95, 99])])),
        "dark_code_fraction_le_005": float(hist[: math.floor(maximum * .05) + 1].sum() / values.size),
        "bright_code_fraction_ge_098": float(hist[math.ceil(maximum * .98):].sum() / values.size),
        "gradient_mean_code_fraction": float(gradients.mean()),
        "gradient_percentiles_code_fraction": [float(v) for v in np.percentile(gradients, [50, 90, 95, 99])],
    }
    result["color_range_enum"] = color_range
    result["metadata_range_normalized"] = None
    # AVColorRange: 1=MPEG (limited), 2=JPEG (full), 0=unspecified.
    # Retain unknown as unknown. Range scaling is not gamma linearization.
    if color_range in (1, 2):
        black, white = ((16 << (bits - 8), 235 << (bits - 8)) if color_range == 1 else (0, maximum))
        scale = white - black
        mapped = (sample * maximum - black) / scale
        result["metadata_range_normalized"] = {
            "range": "limited" if color_range == 1 else "full",
            "black_code": black, "white_code": white,
            "transfer": "Unchanged coded transfer function; not linearized",
            "sampled_mean": float(mapped.mean()), "sampled_stddev": float(mapped.std()),
            "sampled_percentiles": [float(v) for v in np.percentile(mapped, [1, 5, 50, 95, 99])],
            "dark_fraction_le_005": float(hist[: math.floor(black + scale * .05) + 1].sum() / values.size),
            "bright_fraction_ge_098": float(hist[math.ceil(black + scale * .98):].sum() / values.size),
            "below_black_fraction": float(hist[:black].sum() / values.size),
            "above_white_fraction": float(hist[white + 1:].sum() / values.size),
            "gradient_mean": float(gradients.mean() * maximum / scale),
        }
    return result


def summarize_rows(rows, requested, np):
    if not rows:
        return {"frame_count": 0, "completed_duration": False}
    observed = (rows[-1]["pc_monotonic_ns"] - rows[0]["pc_monotonic_ns"]) / 1e9
    pts = [r["pts_seconds"] for r in rows if r["pts_seconds"] is not None]
    pts_gaps = np.diff(pts) if len(pts) > 1 else np.array([])
    pc_gaps = np.diff([r["pc_monotonic_ns"] for r in rows]) / 1e9
    return {
        "frame_count": len(rows), "observed_seconds": observed,
        "decode_fps": (len(rows) - 1) / observed if observed > 0 else None,
        "first_pts_seconds": pts[0] if pts else None,
        "last_pts_seconds": pts[-1] if pts else None,
        "all_frames_have_pts": len(pts) == len(rows),
        "pts_strictly_monotonic": bool(len(pts_gaps) and np.all(pts_gaps > 0)),
        "pts_gap_p95_seconds": float(np.percentile(pts_gaps, 95)) if len(pts_gaps) else None,
        "pts_gap_max_seconds": float(pts_gaps.max()) if len(pts_gaps) else None,
        "pc_gap_p95_seconds": float(np.percentile(pc_gaps, 95)) if len(pc_gaps) else None,
        "pc_gap_max_seconds": float(pc_gaps.max()) if len(pc_gaps) else None,
        "dimensions_and_formats": [list(item) for item in sorted({(r["width"], r["height"], r["pixel_format"]) for r in rows})],
        "completed_duration": observed >= requested - .25,
    }


def worker(args):
    out = Path(args.out) / args.worker
    out.mkdir(parents=True, exist_ok=True)
    result = {"kind": args.worker, "url": args.url, "requested_seconds": args.duration,
              "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
              "geometry_label": args.geometry_label, "error": None, "startup_errors": [],
              "snapshots": [], "statistics_samples": 0,
              "measurement_limits": [
                  "Decoded luma code values are not linear sensor RAW or physical illumination.",
                  "Dark/bright code fractions are not sensor underexposure/saturation measurements.",
                  "Depth mount is a colour visualization; its pixels do not establish metric depth accuracy.",
                  "Main10/8-bit transfer functions and rectification may differ; these summaries do not prove an image-quality improvement.",
                  "PC decode arrival timestamps are not exposure timestamps or camera synchronization proof."]}
    container = None
    recording = None
    rows = []
    success = False
    try:
        import av
        import cv2
        import numpy as np
        result["versions"] = {"python": sys.version, "pyav": av.__version__, "opencv": cv2.__version__, "numpy": np.__version__}
        started = time.monotonic()
        startup_deadline = started + args.startup_timeout
        first_time = None
        stats_time = None
        snapshot_index = 0
        snapshot_offsets = np.linspace(0, max(0, args.duration - .5), args.snapshots).tolist()
        with (out / "frames.jsonl").open("w", encoding="utf-8", buffering=1) as frame_log, \
             (out / "luma_statistics.jsonl").open("w", encoding="utf-8", buffering=1) as stats_log:
            while first_time is None and time.monotonic() < startup_deadline:
                try:
                    options = ({"rtsp_transport": "tcp", "fflags": "nobuffer", "flags": "low_delay", "max_delay": "0"}
                               if args.url.lower().startswith(("rtsp://", "rtsps://")) else {})
                    container = av.open(args.url, options=options,
                                        timeout=(3.0, 4.0))
                    stream = container.streams.video[0]
                    result["stream"] = metadata(stream, ("index", "time_base", "average_rate", "base_rate", "guessed_rate", "start_time", "duration", "frames"))
                    result["codec"] = metadata(stream.codec_context, ("name", "profile", "width", "height", "pix_fmt", "format", "color_range", "colorspace", "color_primaries", "color_trc"))
                    result["stream_metadata"] = dict(stream.metadata)
                    if args.record:
                        # One container per connection attempt. Before the first
                        # frame a failure restarts this file; any successful run
                        # is continuous, with no hidden reconnect after startup.
                        recording = av.open(str(out / "stream.mkv"), mode="w", format="matroska")
                        recorded_stream = recording.add_stream_from_template(stream)
                    for packet in container.demux(stream):
                        frames = packet.decode()
                        if recording is not None and packet.dts is not None:
                            packet.stream = recorded_stream
                            recording.mux(packet)
                        for frame in frames:
                            now = time.monotonic()
                            if first_time is None:
                                first_time = now
                                result["startup_seconds"] = now - started
                                result["first_frame"] = metadata(frame, ("color_range", "colorspace", "color_primaries", "color_trc", "pict_type", "key_frame", "time_base"))
                            elapsed = now - first_time
                            row = {"index": len(rows), "pc_monotonic_ns": time.monotonic_ns(),
                                   "pc_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                                   "elapsed_seconds": elapsed, "pts": frame.pts,
                                   "time_base": str(frame.time_base),
                                   "pts_seconds": float(frame.pts * frame.time_base) if frame.pts is not None and frame.time_base is not None else None,
                                   "width": frame.width, "height": frame.height, "pixel_format": frame.format.name,
                                   "color_range": frame.color_range, "colorspace": frame.colorspace,
                                   "key_frame": bool(frame.key_frame)}
                            rows.append(row)
                            frame_log.write(json.dumps(row) + "\n")
                            want_stats = stats_time is None or now - stats_time >= args.stats_interval
                            want_snapshot = snapshot_index < len(snapshot_offsets) and elapsed >= snapshot_offsets[snapshot_index]
                            if want_stats or want_snapshot:
                                values, bits, storage = native_luma(frame, np)
                                if want_stats:
                                    stats = {"frame_index": row["index"], "pts_seconds": row["pts_seconds"], "elapsed_seconds": elapsed,
                                             "storage": storage, **luma_statistics(values, bits, np, frame.color_range)}
                                    if args.worker == "stereo" and frame.width % 2 == 0:
                                        half = frame.width // 2
                                        stats["left"] = luma_statistics(values[:, :half], bits, np, frame.color_range)
                                        stats["right"] = luma_statistics(values[:, half:], bits, np, frame.color_range)
                                    stats_log.write(json.dumps(stats) + "\n")
                                    result["statistics_samples"] += 1
                                    stats_time = now
                                if want_snapshot:
                                    stem = f"snapshot-{snapshot_index:02d}-frame-{row['index']:06d}"
                                    png = stem + ".png"
                                    if not cv2.imwrite(str(out / png), frame.to_ndarray(format="bgr24")):
                                        raise RuntimeError(f"Could not write {png}")
                                    snap = {**row, "png": png, "coded_bits": bits, "native_luma": None,
                                            "png_conversion": "PyAV/libswscale bgr24; inspect native luma NPY for exact decoded code values."}
                                    if args.worker == "stereo":
                                        snap["native_luma"] = stem + "-luma.npy"
                                        np.save(out / snap["native_luma"], values, allow_pickle=False)
                                    result["snapshots"].append(snap)
                                    snapshot_index += 1
                            if elapsed >= args.duration:
                                success = True
                                break
                        if success:
                            break
                        if first_time is None and time.monotonic() >= startup_deadline:
                            break
                    if first_time is not None:
                        break
                    raise RuntimeError("RTSP stream ended before the first decoded frame")
                except Exception as error:
                    if first_time is not None:
                        raise
                    result["startup_errors"].append({"elapsed_seconds": time.monotonic() - started, "error": repr(error)})
                    time.sleep(.25)
                finally:
                    if recording is not None:
                        recording.close()
                        recording = None
                    if container is not None:
                        container.close()
                        container = None
        result.update(summarize_rows(rows, args.duration, np))
        if first_time is None:
            result["error"] = "No decoded frame before startup deadline"
        elif not success:
            result["error"] = "Stream ended before requested observation duration"
        elif not result["pts_strictly_monotonic"] or not result["all_frames_have_pts"]:
            result["error"] = "Missing or non-monotonic presentation timestamps"
    except BaseException as error:
        result["error"] = repr(error)
        result["traceback"] = traceback.format_exc()
        try:
            import numpy as np
            result.update(summarize_rows(rows, args.duration, np))
        except ImportError:
            result["frame_count"] = len(rows)
    finally:
        result["finished_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        write_json(out / "summary.json", result)
    print(json.dumps({"kind": args.worker, "frame_count": result.get("frame_count", 0),
                      "decode_fps": result.get("decode_fps"), "error": result["error"]}))
    return 0 if result["error"] is None and result.get("completed_duration", False) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="rtsp://192.168.137.226:8554")
    parser.add_argument("--stereo-url", help="Override BASE/stereo")
    parser.add_argument("--depth-url", help="Override BASE/depth")
    parser.add_argument("--out", required=True, help="Fresh evidence directory; existing output is not overwritten")
    parser.add_argument("--duration", type=float, default=60)
    parser.add_argument("--startup-timeout", type=float, default=30)
    parser.add_argument("--stats-interval", type=float, default=1)
    parser.add_argument("--snapshots", type=int, default=7)
    parser.add_argument("--record", action="store_true", help="Also remux original encoded packets into stream.mkv")
    parser.add_argument("--geometry-label", default="unspecified", help="Evidence label, e.g. rectified Main10 or unrectified shared8")
    parser.add_argument("--worker", choices=("stereo", "depth"), help=argparse.SUPPRESS)
    parser.add_argument("--url", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.duration <= 0 or not 0 < args.startup_timeout <= 30 or args.stats_interval <= 0 or not 1 <= args.snapshots <= 20:
        parser.error("duration/stats-interval must be positive, startup-timeout in (0,30], snapshots in [1,20]")
    if args.worker:
        return worker(args)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    manifest = {"started_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "arguments": vars(args),
                "hard_limit_seconds": args.duration + 45, "streams": {}, "success": False}
    write_json(out / "collection.json", manifest)
    children = {}
    logs = []
    try:
        for kind, url in (("stereo", args.stereo_url or args.base_url.rstrip("/") + "/stereo"),
                          ("depth", args.depth_url or args.base_url.rstrip("/") + "/depth")):
            command = [sys.executable, str(Path(__file__).resolve()), "--worker", kind, "--url", url,
                       "--out", str(out), "--duration", str(args.duration), "--startup-timeout", str(args.startup_timeout),
                       "--stats-interval", str(args.stats_interval), "--snapshots", str(args.snapshots),
                       "--geometry-label", args.geometry_label]
            if args.record:
                command.append("--record")
            log = (out / f"{kind}-worker.log").open("w", encoding="utf-8")
            logs.append(log)
            children[kind] = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + args.duration + 45
        while any(child.poll() is None for child in children.values()) and time.monotonic() < deadline:
            time.sleep(.2)
    finally:
        for kind, child in children.items():
            timed_out = child.poll() is None
            if timed_out:
                child.kill()
            child.wait(timeout=10)
            summary_path = out / kind / "summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {"error": "Worker did not produce summary; inspect partial JSONL and worker log"}
            summary["worker_exit_code"] = child.returncode
            summary["parent_terminated"] = timed_out
            if timed_out:
                summary["error"] = "Worker exceeded absolute collection deadline; partial files preserved"
            manifest["streams"][kind] = summary
        for log in logs:
            log.close()
        manifest["finished_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        manifest["success"] = len(manifest["streams"]) == 2 and all(
            item.get("worker_exit_code") == 0 and item.get("completed_duration") and not item.get("error")
            for item in manifest["streams"].values())
        write_json(out / "collection.json", manifest)
    print(json.dumps({"out": str(out), "success": manifest["success"],
                      "streams": {kind: {key: summary.get(key) for key in ("frame_count", "decode_fps", "observed_seconds", "pts_gap_p95_seconds", "error")}
                                  for kind, summary in manifest["streams"].items()}}, indent=2))
    return 0 if manifest["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
