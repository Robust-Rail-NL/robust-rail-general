#!/usr/bin/env python3
"""Summarize one or more planner-timing-{single,array}.sbatch output
directories into one CSV: condition, task, node, start_time, spread (within
that condition, vs the earliest task), copy_duration (local-copy sif, if
any), time_to_planning, search_time, total_wall, returncode.

Usage: summarize_planner_timing.py <dir> [<dir> ...] [--output FILE]

Each <dir> is either a single task's own output directory (has
metadata.json/timestamped.log directly in it -- condition "single") or an
array condition's OUT_BASE (has task_0/, task_1/, ... subdirectories).
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

PLANNING_RE = re.compile(r"^\S+ Planning\.\.\.")
DONE_RE = re.compile(r"^\S+ (Solved problem|Failed to find a solution\.)")


def _read_json_robust(path: Path) -> dict:
    """Parse path as JSON, tolerating (and warning about) trailing extra
    data -- e.g. from the two-concurrent-writers corruption a SLURM requeue
    could cause before run_planner_direct.py's metadata.json write became
    atomic (2026-10-17)."""
    text = path.read_text()
    obj, end = json.JSONDecoder().raw_decode(text)
    if text[end:].strip():
        print(f"WARNING: {path} has trailing data after its first JSON document "
              f"(likely leftover from a past concurrent-write corruption) -- using the first one.",
              file=sys.stderr)
    return obj


def _phase_timestamps(log_path: Path) -> tuple[float | None, float | None]:
    """(time of the "Planning..." line, time of the solved/failed line), or
    None for either not found -- e.g. a run that never got that far."""
    planning_ts = done_ts = None
    if not log_path.exists():
        return None, None
    for line in log_path.read_text(errors="replace").splitlines():
        ts_str, _, rest = line.partition(" ")
        try:
            ts = float(ts_str)
        except ValueError:
            continue
        if planning_ts is None and rest.startswith("Planning..."):
            planning_ts = ts
        elif done_ts is None and (rest.startswith("Solved problem")
                                  or rest.startswith("Failed to find a solution.")):
            done_ts = ts
    return planning_ts, done_ts


def _task_dirs(path: Path) -> list[Path]:
    if (path / "metadata.json").exists():
        return [path]
    return sorted(path.glob("task_*"), key=lambda p: int(p.name.removeprefix("task_")))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dirs", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, metavar="FILE",
                        help="Write CSV here instead of stdout.")
    args = parser.parse_args()

    rows = []
    for base in args.dirs:
        task_dirs = _task_dirs(base)
        if not task_dirs:
            print(f"WARNING: no metadata.json under {base}", file=sys.stderr)
            continue
        starts = []
        for task_dir in task_dirs:
            meta = _read_json_robust(task_dir / "metadata.json")
            starts.append(meta["start_time"])
        earliest = min(starts)

        for task_dir in task_dirs:
            meta = _read_json_robust(task_dir / "metadata.json")
            planning_ts, done_ts = _phase_timestamps(task_dir / "timestamped.log")
            start = meta["start_time"]
            end = meta["end_time"]
            copy_duration = (meta["copy_end"] - meta["copy_start"]
                             if "copy_start" in meta else None)
            rows.append({
                "condition": meta["condition"],
                "task": meta["task_index"],
                "node": meta["node"],
                "start_time": f"{start:.3f}",
                "start_spread_s": f"{start - earliest:.3f}",
                "copy_duration_s": f"{copy_duration:.3f}" if copy_duration is not None else "",
                "time_to_planning_s": f"{planning_ts - start:.3f}" if planning_ts else "",
                "search_time_s": f"{done_ts - planning_ts:.3f}" if (planning_ts and done_ts) else "",
                "total_wall_s": f"{end - start:.3f}",
                "returncode": meta["returncode"],
            })

    fieldnames = ["condition", "task", "node", "start_time", "start_spread_s",
                 "copy_duration_s", "time_to_planning_s", "search_time_s",
                 "total_wall_s", "returncode"]
    out = open(args.output, "w", newline="") if args.output else sys.stdout
    try:
        writer = csv.DictWriter(out, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    finally:
        if args.output:
            out.close()
    print(f"Wrote {len(rows)} row(s)" + (f" to {args.output}" if args.output else ""),
          file=sys.stderr)


if __name__ == "__main__":
    main()
