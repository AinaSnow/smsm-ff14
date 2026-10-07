"""Record a human-observed game check and optional measured frame-time CSV.

This tool does not capture frames, collect timings, or infer shader execution.
"""
import argparse
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics
import uuid
from manage_preview import JOURNAL, ROOT, digest, snapshot


def percentile(values, fraction):
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def summarize_frames(path, column, process=None):
    values = []
    filtered = 0
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or column not in reader.fieldnames:
            raise ValueError(f"Missing frame-time column {column}; select a column measured in milliseconds")
        if process and "Application" not in reader.fieldnames:
            raise ValueError("--process requires an Application column")
        for line, row in enumerate(reader, 2):
            if process and row["Application"].casefold() != process.casefold():
                filtered += 1
                continue
            try:
                value = float(row[column])
            except (ValueError, TypeError):
                raise ValueError(f"Invalid frame time at CSV line {line}") from None
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"Nonpositive/nonfinite frame time at CSV line {line}")
            values.append(value)
    if not values:
        raise ValueError("No matching valid frames")
    return {"samples": len(values), "filtered_other_process_rows": filtered,
            "column_ms": column, "csv_sha256": digest(path.read_bytes()),
            "mean_ms": statistics.mean(values), "median_ms": statistics.median(values),
            "p95_ms": percentile(values, .95), "p99_ms": percentile(values, .99),
            "max_ms": max(values), "aggregate_fps": 1000 / statistics.mean(values),
            "note": "Submitted frame intervals, not isolated GPU shader cost. No outliers discarded."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-root", type=Path, required=True)
    parser.add_argument("--scenario", required=True, choices=("teleport", "combat", "indoor-outdoor", "effect-comparison", "reload-check"))
    parser.add_argument("--outcome", required=True, choices=("normal", "issue", "inconclusive"))
    parser.add_argument("--notes", required=True)
    parser.add_argument("--settings", required=True, help="Resolution, AA/upscaling, frame cap; keep the same for paired checks")
    parser.add_argument("--pair", help="Shared label for matched A/B observations")
    parser.add_argument("--condition", choices=("on", "off", "baseline"), default="baseline")
    parser.add_argument("--frames", type=Path)
    parser.add_argument("--column", default="frame_time_ms")
    parser.add_argument("--process", help="Exact Application value for filtering a multi-process CSV")
    parser.add_argument("--fps-range", nargs=2, type=float, metavar=("MIN", "MAX"), help="Manually observed FPS range, not a frame-time measurement")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts/validation")
    args = parser.parse_args()
    if args.fps_range and (not all(math.isfinite(v) and v > 0 for v in args.fps_range) or args.fps_range[0] > args.fps_range[1]):
        parser.error("FPS range must be positive finite values in ascending order")
    game = (args.client_root / "game").resolve(strict=True)
    if (game / JOURNAL).exists():
        raise ValueError("Recover the interrupted installation before recording its state")
    files, manifest, state = snapshot(game)
    report = {"recorded_at_utc": datetime.now(timezone.utc).isoformat(),
              "client_build": (game / "ffxivgame.ver").read_text().strip(),
              "package_sha256": digest(files["SMSM-preview.json"]) if manifest else None,
              "effects": state["effects"] if state else None,
              "selection_application": state["application"] if state else "unknown",
              "scenario": args.scenario, "human_observed_outcome": args.outcome,
              "notes": args.notes, "settings": args.settings, "pair": args.pair,
              "condition": args.condition, "manual_fps_range": args.fps_range,
              "frame_times": summarize_frames(args.frames, args.column, args.process) if args.frames else None,
              "shader_execution_proven": False, "global_runtime_verified": False}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex + ".json")
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError) as error:
        raise SystemExit(f"ERROR: {error}")
