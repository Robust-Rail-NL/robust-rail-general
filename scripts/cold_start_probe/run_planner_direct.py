#!/usr/bin/env python3
"""Run the planner directly via apptainer, bypassing run_planner.py entirely.

run_planner.py's own _run_scenario_single captures the container's
stdout/stderr straight into planner.out/.err (docker_utils.run_container) --
it never reaches run_planner.py's own stdout, so wrapping run_planner.py
itself with a line-timestamper (the first cold-warm probe's approach) only
ever timestamps the outer driver's own two or three print lines, never the
planner's actual "Planning..."/"Solved problem..." lines. This builds the
identical apptainer command run_planner.py's _run_scenario_single does (same
mounts, --env JULIA_DEPOT_PATH, --pwd, --writable-tmpfs -- see run_planner.py's
own CONTAINER_WORKDIR/CONTAINER_ENV) and pipes its combined stdout+stderr
through a line-by-line timestamper directly, for real phase timing.

Writes, under <out_dir>:
  timestamped.log   one "<unix-time> <line>" per line of combined stdout/stderr
  metadata.json     condition, task index, node, scenario, which .sif was
                    used (and its identity), start/end (and copy, if
                    --copy-sif-to was given) timestamps, exit code
  plan.json         the planner's actual output, same as a normal run

--sif PATH: use this .sif instead of the default staged one (e.g. a
node-local copy already in place).
--copy-sif-to DIR: copy the default staged .sif into DIR first (timed
separately, recorded in metadata.json as copy_start/copy_end), then run
against that copy. For condition (c) -- does reading from node-local
storage remove the cold-start slowdown.
--warmup: run the exact same command once first, output discarded, before
the real timed run -- a per-task self-warm-up (adapted from "one dummy run
per node first": which physical node a task lands on isn't known before
SLURM dispatches it, so pre-warming specific nodes ahead of time isn't
mechanically possible -- warming each task's own node right before its own
timed run is the closest equivalent).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # scripts/cold_start_probe/ -> repo root
sys.path.insert(0, str(ROOT))
from scripts.docker_utils import DEFAULT_SIF_CACHE_DIR, image_identity, sif_path  # noqa: E402

IMAGE = "ghcr.io/robust-rail-nl/planner:edge"
LOCATION = "Location_KleineBinckhorst"


def _run_once(cmd: list[str], log_path: Path | None) -> int:
    """Run cmd, optionally timestamping each line of its combined output to
    log_path. log_path=None discards output (the --warmup throwaway run)."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1)
    if log_path is not None:
        with open(log_path, "w") as log:
            for line in proc.stdout:
                log.write(f"{time.time():.3f} {line}")
                log.flush()
    else:
        for _ in proc.stdout:
            pass
    proc.wait()
    return proc.returncode


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--sif", type=Path, help="Use this .sif instead of the default staged one.")
    parser.add_argument("--copy-sif-to", type=Path, metavar="DIR",
                        help="Copy the default staged .sif into DIR first, then run against that copy.")
    parser.add_argument("--warmup", action="store_true",
                        help="Run the same command once first, discarded, before the timed run.")
    parser.add_argument("--condition", default="unknown")
    parser.add_argument("--task-index", type=int, default=0)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "condition": args.condition,
        "task_index": args.task_index,
        "node": os.environ.get("SLURMD_NODENAME", "unknown"),
        "scenario": str(args.scenario),
    }

    default_sif = sif_path(IMAGE, DEFAULT_SIF_CACHE_DIR)
    sif = args.sif or default_sif

    if args.copy_sif_to:
        args.copy_sif_to.mkdir(parents=True, exist_ok=True)
        local_sif = args.copy_sif_to / default_sif.name
        metadata["copy_start"] = time.time()
        shutil.copy2(default_sif, local_sif)
        metadata["copy_end"] = time.time()
        sif = local_sif

    metadata["sif_used"] = str(sif)
    metadata["sif_identity"] = image_identity("apptainer", IMAGE, sif.parent)

    scenario_dir = args.scenario.resolve().parent
    location_dir = (ROOT / LOCATION).resolve()
    output_dir = args.out_dir.resolve()

    cmd = [
        "apptainer", "run", "--writable-tmpfs", "--pwd", "/app",
        "--env", "JULIA_DEPOT_PATH=/tmp/julia-depot:/opt/julia-depot",
        "--bind", f"{location_dir}:/app/database",
        "--bind", f"{output_dir}:/app/output",
        "--bind", f"{scenario_dir}:/app/scenario",
        str(sif),
        "--location", "/app/database/location.json",
        "--scenario", f"/app/scenario/{args.scenario.name}",
        "--planner", "symbolic-rail",
        "--output", "/app/output/plan.json",
    ]

    if args.warmup:
        _run_once(cmd, None)

    metadata["start_time"] = time.time()
    metadata["returncode"] = _run_once(cmd, output_dir / "timestamped.log")
    metadata["end_time"] = time.time()

    # Write via a temp file + atomic rename, not a direct write_text(): a
    # SLURM requeue (two processes briefly both believing they own this
    # task, e.g. after a node failure) could otherwise interleave two
    # separate writes to the same path and leave two JSON documents
    # concatenated in one file -- found 2026-10-17 ("Extra data" from
    # json.loads() reading metadata.json back). os.replace() is atomic even
    # on a shared/network filesystem the way a raw concurrent write isn't:
    # whichever write wins, the file is always exactly one complete, valid
    # JSON document, never a half-written or concatenated one.
    tmp_path = output_dir / "metadata.json.tmp"
    tmp_path.write_text(json.dumps(metadata, indent=2) + "\n")
    os.replace(tmp_path, output_dir / "metadata.json")
    print(f"[{args.condition} task {args.task_index} node {metadata['node']}] "
          f"{metadata['end_time'] - metadata['start_time']:.1f}s, exit {metadata['returncode']}")


if __name__ == "__main__":
    main()
