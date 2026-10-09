#!/usr/bin/env python3
"""Run one (instance, tool[, seed]) attempt from a scripts/slurm_manifest.py
manifest -- what one SLURM array task actually executes.

Reuses run_experiment.py's own _run_and_record/_version_for rather than
reimplementing the solver-or-planner-then-evaluator sequence, so an array
task and a --jobs N local run of the same attempt behave identically -- any
future fix to that sequence covers both paths at once, and this script stays
a thin adapter (manifest row -> _run_and_record call) rather than a second
copy of the pipeline logic.

Takes the same experiment JSON as run_experiment.py, so versions, budget,
planner and departure-delay tolerance are exactly what the file says.

--index defaults to $SLURM_ARRAY_TASK_ID so scripts/slurm/
run_experiment_array.sbatch doesn't have to pass it explicitly; passing
--index directly also lets this be run/tested off an actual array job.

Always --engine apptainer: this script exists for the SLURM path only, never
called from run_experiment.py's own docker path.
"""

import argparse
import csv
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import run_experiment  # noqa: E402
from scripts import experiment_spec  # noqa: E402
from scripts.docker_utils import DEFAULT_SIF_CACHE_DIR  # noqa: E402


def _read_row(manifest: Path, index: int) -> dict:
    with open(manifest, newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            if int(row["index"]) == index:
                return row
    sys.exit(f"ERROR: no row with index {index} in {manifest}.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run one attempt from a scripts/slurm_manifest.py manifest -- what one SLURM "
                    "array task actually executes."
    )
    parser.add_argument("--manifest", required=True, type=Path, metavar="FILE")
    parser.add_argument("--index", type=int, metavar="N",
                        help="Manifest row to run (default: $SLURM_ARRAY_TASK_ID).")
    parser.add_argument("--experiment", required=True, type=Path, metavar="FILE",
                        help="The experiment JSON, as for run_experiment.py.")
    parser.add_argument("--output-dir", required=True, type=Path, metavar="DIR")
    parser.add_argument("--sif-cache-dir", type=Path, default=DEFAULT_SIF_CACHE_DIR, metavar="DIR")
    args = parser.parse_args()

    index = args.index
    if index is None:
        env_index = os.environ.get("SLURM_ARRAY_TASK_ID")
        if env_index is None:
            sys.exit("ERROR: --index not given and $SLURM_ARRAY_TASK_ID not set -- pass --index "
                     "explicitly when running this off an actual array job.")
        index = int(env_index)

    try:
        spec = experiment_spec.load(args.experiment)
    except (OSError, ValueError) as exc:
        sys.exit(f"ERROR: {exc}")
    versions = spec[experiment_spec.VERSIONS_KEY]

    row = _read_row(args.manifest, index)
    instance, tool = row["instance"], row["tool"]
    seed = int(row["seed"]) if row["seed"] else spec["seed"]
    tool_dir = args.output_dir / row["tool_dir"]

    key = f"solver_seed{seed}" if (tool == "solver" and row["seed"]) else tool
    print(f"[task {index}] {instance} [{key}] -> {tool_dir}", flush=True)

    results = {}
    run_experiment._run_and_record(
        tool, spec["location"], instance, tool_dir,
        versions["solver"], versions["planner"], versions["evaluator"],
        False, spec["max_duration"], seed, spec["planner"],
        spec["departure_delay_fraction"], results, key,
        "apptainer", args.sif_cache_dir,
    )


if __name__ == "__main__":
    main()
