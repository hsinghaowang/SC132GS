#!/usr/bin/env python3
"""Audit existing capture CSV without inventing host sample timestamps.

Example:
  python audit_imu.py --csv ../gs130wi_imu/capture-wired-irq-30s.csv 
    --summary ../gs130wi_imu/capture-wired-irq-30s-summary.json --output audit.json

The audit is capture evidence, not a SLAM performance measurement.
Exit codes: 0 = capture integrity passed, 1 = integrity failed, 2 = input error.
Read live_vio_time_ready separately: capture success does not imply synchronization.
"""
import argparse
import csv
import json
import math
from pathlib import Path


def audit(csv_path, summary_path):
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    required = {"index", "valid", "sensor_elapsed_ns", "host_read_begin_ns",
                "host_read_end_ns", "host_interrupt_ns", "ax_g", "ay_g", "az_g",
                "gx_dps", "gy_dps", "gz_dps"}
    count = invalid = repeated_interrupt_rows = 0
    first_sensor = last_sensor = first_host = last_host = None
    last_interrupt = None
    deltas = []
    errors = set()
    with csv_path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError("missing columns: " + ", ".join(sorted(missing)))
        for row in reader:
            index = int(row["index"])
            valid = int(row["valid"])
            sensor = int(row["sensor_elapsed_ns"])
            begin = int(row["host_read_begin_ns"])
            end = int(row["host_read_end_ns"])
            if index != count:
                errors.add("non_contiguous_sample_index")
            if valid != 1:
                invalid += 1
                errors.add("invalid_sample")
            if sensor < 0 or begin < 0 or end < begin:
                errors.add("invalid_timestamp")
            if last_sensor is not None:
                delta = sensor - last_sensor
                deltas.append(delta)
                if delta <= 0:
                    errors.add("non_monotonic_sensor_time")
                if end < last_host:
                    errors.add("non_monotonic_host_read_time")
            for field in ("ax_g", "ay_g", "az_g", "gx_dps", "gy_dps", "gz_dps"):
                if not math.isfinite(float(row[field])):
                    errors.add("non_finite_measurement")
            interrupt = int(row["host_interrupt_ns"]) if row["host_interrupt_ns"] else None
            if interrupt is not None and interrupt == last_interrupt:
                repeated_interrupt_rows += 1
            if first_sensor is None:
                first_sensor, first_host = sensor, end
            last_sensor, last_host, last_interrupt = sensor, end, interrupt
            count += 1
    if count < 2:
        errors.add("insufficient_samples")
    if summary.get("status") != "ok":
        errors.add("capture_summary_not_ok")
    if summary.get("samples") != count or summary.get("valid") != count - invalid:
        errors.add("summary_count_mismatch")
    sensor_span = (last_sensor - first_sensor) if count > 1 else 0
    host_span = (last_host - first_host) if count > 1 else 0
    return {
        "schema_version": 1,
        "evidence_type": "historical_imu_capture_integrity",
        "csv": str(csv_path.resolve()),
        "summary": str(summary_path.resolve()),
        "samples": count,
        "invalid_samples": invalid,
        "capture_integrity_passed": not errors,
        "errors": sorted(errors),
        "sensor_elapsed_duration_s": sensor_span / 1e9,
        "host_read_duration_s": host_span / 1e9,
        "sensor_counter_rate_hz": (count - 1) * 1e9 / sensor_span if sensor_span > 0 else None,
        "host_read_observed_rate_hz": (count - 1) * 1e9 / host_span if host_span > 0 else None,
        "sensor_delta_min_ns": min(deltas) if deltas else None,
        "sensor_delta_max_ns": max(deltas) if deltas else None,
        "repeated_batch_irq_rows": repeated_interrupt_rows,
        "configuration_restored": summary.get("restored") is True,
        "live_vio_time_ready": summary.get("host_sample_time_validated") is True,
        "time_readiness_source": "capture summary claim; no independent clock validation performed by this audit",
        "unit_conversion_required": {"g_to_m_s2": 9.80665, "deg_s_to_rad_s": math.pi / 180},
        "limitations": [
            "sensor_elapsed_ns is a relative sensor counter timeline",
            "host_interrupt_ns is a batch notification, not each sample time",
            "sensor and host rates do not establish offset or drift calibration",
            "camera exposure synchronization and SLAM performance are not evaluated"
        ]
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = audit(args.csv, args.summary)
    except (OSError, ValueError, KeyError, TypeError, csv.Error) as error:
        parser.exit(2, f"Input error: {error}\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in (
        "samples", "capture_integrity_passed", "sensor_counter_rate_hz",
        "host_read_observed_rate_hz", "live_vio_time_ready", "errors")}, indent=2))
    return 0 if result["capture_integrity_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
