#!/usr/bin/env python3
"""Enumerate a run_experiment.py sweep's work units into a manifest -- one
line per SLURM array task index -- for scripts/slurm_run_task.py to read.

Takes the same experiment JSON run_experiment.py does (see
scripts/experiment_spec.py), so the sweep's tools, seeds and instances come
from the one file that records the run. Expands its "scenarios" block into
<location>/configurations/<name>/ -- run_generator.py needs those configs, and
the instances are named by them -- and prints the generator command to run
next. Runs no container itself; this only enumerates work.

Reuses run_experiment.py's own instance resolution (_instances_from_configs)
and mirrors _run_instance's per-tool/per-seed loop, rather than
reimplementing either, so an array-job sweep and a local sweep of the same
file produce the same folder layout. One difference: a local sweep stops at the
first seed that solves an instance, which independent array tasks cannot do,
so the array runs every seed. Reporting only asks whether any seed solved, so
the results are the same.
"""

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import run_experiment  # noqa: E402
from scripts import experiment_spec  # noqa: E402


def _tool_dirs(instance: str, tools: list[str], num_seeds: int | None):
    """Yield (tool, seed, tool_dir) for one instance, matching
    run_experiment._run_instance's own loop exactly (same FOLDER_NAMES,
    same seed<i> subdirectory convention).
    """
    for tool in tools:
        if tool == "solver" and num_seeds:
            for s in range(1, num_seeds + 1):
                yield tool, s, f"{instance}/{run_experiment.FOLDER_NAMES[tool]}/seed{s}"
        else:
            yield tool, None, f"{instance}/{run_experiment.FOLDER_NAMES[tool]}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enumerate an experiment's work units into a manifest for "
                    "scripts/slurm_run_task.py, one line per SLURM array task index. Run "
                    "before run_generator.py and before submitting the array job."
    )
    parser.add_argument("experiment", metavar="FILE", type=Path,
                        help="The experiment JSON, as for run_experiment.py.")
    parser.add_argument("--output-dir", required=True, type=Path, metavar="DIR",
                        help="Where the sweep's results go (e.g. on /scratch). Not written into "
                             "by this script (that's each array task's job), only used to "
                             "default --manifest's location and to print the ready-to-run "
                             "commands below.")
    parser.add_argument("--manifest", type=Path, metavar="FILE",
                        help="Where to write the manifest (default: <output-dir>/tasks.tsv).")
    args = parser.parse_args()

    if not args.experiment.is_file():
        sys.exit(f"No such experiment file: {args.experiment}")
    try:
        spec = experiment_spec.load(args.experiment)
    except (OSError, ValueError) as exc:
        sys.exit(f"ERROR: {exc}")

    name, location = spec["name"], spec["location"]
    loc = ROOT / location
    if not loc.is_dir():
        sys.exit(f"No such location: {loc}")

    config_dir = run_experiment._generate_configs_from_json(loc, args.experiment, name)
    instances = run_experiment._instances_from_configs(config_dir)
    if not instances:
        sys.exit(f"No scenario_config_*.json files under {config_dir}.")

    manifest_path = args.manifest or (args.output_dir / "tasks.tsv")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for instance in instances:
        for tool, seed, tool_dir in _tool_dirs(instance, spec["tools"], spec["num_seeds"]):
            rows.append({
                "index": len(rows),
                "instance": instance,
                "tool": tool,
                "seed": seed if seed is not None else "",
                "tool_dir": tool_dir,
            })

    with open(manifest_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["index", "instance", "tool", "seed", "tool_dir"],
                                delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)

    seeds_note = f" x up to {spec['num_seeds']} seed(s)" if spec["num_seeds"] else ""
    print(f"Wrote {len(rows)} task(s) ({len(instances)} instance(s) x {spec['tools']}{seeds_note}) "
          f"to {manifest_path}")
    print(f"\nGenerate the scenarios first (login node):\n"
          f"  python3 run_generator.py --location {location} --config-dir {config_dir} "
          f"--version {spec[experiment_spec.VERSIONS_KEY]['generator']} --engine apptainer")
    if rows:
        print(f"\nThen submit with:\n"
              f"  sbatch --array=0-{len(rows) - 1} scripts/slurm/run_experiment_array.sbatch \\\n"
              f"      {manifest_path} {args.experiment} {args.output_dir}")


if __name__ == "__main__":
    main()
