#!/usr/bin/env python3
"""Enumerate a run_experiment.py sweep's work units into a manifest -- one
line per SLURM array task index -- for scripts/slurm_run_task.py to read.

Run after run_generator.py has already produced every scenario (on DelftBlue
that happens directly on the login node -- see docs/slurm-apptainer.md) and
before submitting the array job: this only enumerates work, it runs nothing
itself.

Reuses run_experiment.py's own instance resolution (_instances_from_configs)
and mirrors _run_instance's per-tool/per-seed loop exactly, rather than
reimplementing either, so an array-job sweep and a --jobs N local sweep of
the same flags produce the same set of attempts in the same folder layout.
"""

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import run_experiment  # noqa: E402


def _resolve_instances(loc: Path, config_dir: Path | None, instance: str | None) -> list[str]:
    """Same resolution run_experiment.py's main() does -- see its own
    comments (--config-dir vs --instance vs every scenario under loc) for why
    each branch exists.
    """
    if config_dir:
        instances = run_experiment._instances_from_configs(config_dir)
        if not instances:
            sys.exit(f"No scenario_config_*.json files under {config_dir}.")
        return instances
    if instance:
        return [instance]
    instances = [p.stem.removeprefix("scenario_")
                 for p in sorted(loc.glob("scenarios/scenario_*.json"))]
    if not instances:
        sys.exit(f"No scenario_*.json files under {loc}/scenarios/ -- run run_generator.py first.")
    return instances


def _tool_dirs(instance: str, tools: list, num_seeds: int | None):
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
        description="Enumerate a sweep's work units into a manifest for scripts/slurm_run_task.py, "
                    "one line per SLURM array task index. Run after run_generator.py, before "
                    "submitting the array job."
    )
    parser.add_argument("--location", required=True, metavar="NAME")
    parser.add_argument("--instance", metavar="NAME",
                        help="Same as run_experiment.py's --instance. Mutually exclusive with "
                             "--config-dir.")
    parser.add_argument("--config-dir", type=Path, metavar="DIR",
                        help="Same as run_experiment.py's --config-dir.")
    parser.add_argument("--tools", default="solver,planner", metavar="solver,planner",
                        help="Comma-separated subset of {solver,planner} (default: both).")
    parser.add_argument("--num-seeds", type=int, metavar="N",
                        help="Same as run_experiment.py's --num-seeds.")
    parser.add_argument("--output-dir", required=True, type=Path, metavar="DIR",
                        help="The sweep's --output-dir. Not written into by this script (that's "
                             "each array task's job), only used to default --manifest's location "
                             "and to print the ready-to-run sbatch command below.")
    parser.add_argument("--manifest", type=Path, metavar="FILE",
                        help="Where to write the manifest (default: <output-dir>/tasks.tsv).")
    args = parser.parse_args()

    if args.instance and args.config_dir:
        sys.exit("--instance and --config-dir are mutually exclusive.")

    tools = args.tools.split(",")
    for tool in tools:
        if tool not in ("solver", "planner"):
            sys.exit(f"Unknown tool {tool!r}; --tools takes a subset of solver,planner.")
    if args.num_seeds is not None and "solver" not in tools:
        sys.exit("--num-seeds only applies to the solver; include it in --tools.")

    loc = ROOT / args.location
    if not loc.is_dir():
        sys.exit(f"No such location: {loc}")

    instances = _resolve_instances(loc, args.config_dir, args.instance)
    manifest_path = args.manifest or (args.output_dir / "tasks.tsv")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for instance in instances:
        for tool, seed, tool_dir in _tool_dirs(instance, tools, args.num_seeds):
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

    seeds_note = f" x up to {args.num_seeds} seed(s)" if args.num_seeds else ""
    print(f"Wrote {len(rows)} task(s) ({len(instances)} instance(s) x {tools}{seeds_note}) "
          f"to {manifest_path}")
    if rows:
        print(f"\nSubmit with:\n"
              f"  sbatch --array=0-{len(rows) - 1} scripts/slurm/run_experiment_array.sbatch \\\n"
              f"      {manifest_path} {args.location} {args.output_dir}")


if __name__ == "__main__":
    main()
