#!/usr/bin/env python3
"""Run the planner docker image on all scenario_solver_*.json files.

Replaces the HIP solver step: converts each solver-format scenario to PDDL,
plans, and converts the result back to TORS JSON at plans/plan_<suffix>.json —
the same output convention run_evaluator.py already consumes.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
CONTAINER_DB = "/app/database"

# These mirror the other steps' --version choices so the pipeline can pass
# --version uniformly, but no planner image is published under any tag yet —
# the planner image is built locally (see planning-approach-refactor/Dockerfile)
# until it's ready to publish, which is why every key maps to the same image.
PLANNER_DOCKER_IMAGE_VERSIONS = {
    "legacy": "planner:latest",
    "2.0.0": "planner:latest",
    "2.0.0-assert": "planner:latest",
    "local": "planner:latest",
}


def _scenario_name(scenario: Path) -> str:
    return scenario.stem.removeprefix("scenario_solver_")


def _run_scenario(docker_image: str, location_dir: Path, scenario: Path, planner: str, dry_run: bool) -> bool:
    name = _scenario_name(scenario)
    plan_name = f"plan_{name}.json"

    cmd = [
        "docker", "run", "--rm",
        *(["--user", f"{os.getuid()}:{os.getgid()}"] if sys.platform != "win32" else []),
        "--mount", f"type=bind,source={location_dir.resolve()},target={CONTAINER_DB}",
        docker_image,
        "--location", f"{CONTAINER_DB}/location.json",
        "--scenario", f"{CONTAINER_DB}/scenarios/{scenario.name}",
        "--planner", planner,
        "--output", f"{CONTAINER_DB}/plans/{plan_name}",
    ]

    print(f"  {scenario.name}  ->  {plan_name}")
    if dry_run:
        print(f"    [dry-run] {' '.join(cmd)}")
        return True

    plans_dir = location_dir / "plans"
    plans_dir.mkdir(exist_ok=True)
    out_file = plans_dir / f"plan_{name}.out"
    err_file = plans_dir / f"plan_{name}.err"

    returncode = None
    ok = False
    try:
        with open(out_file, "w") as fout, open(err_file, "w") as ferr:
            result = subprocess.run(cmd, stdout=fout, stderr=ferr)
        returncode = result.returncode
        ok = returncode == 0
    except Exception as exc:
        print(f"    ERROR: {exc}", file=sys.stderr)

    with open(err_file, "a") as f:
        f.write(f"--- exit: {returncode if returncode is not None else 'error'}\n")
    out_lines = len(out_file.read_text().splitlines()) if out_file.exists() else 0
    err_lines = len(err_file.read_text().splitlines()) if err_file.exists() else 0
    if ok and err_lines <= 1:
        err_file.unlink(missing_ok=True)
        err_lines = 0
    err_part = f"  stderr: {err_lines}L" if err_lines else ""
    print(f"    stdout: {out_lines}L{err_part}  (exit {returncode})")

    if not ok and returncode is not None:
        print(f"    FAILED (exit {returncode})", file=sys.stderr)
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the planner on all scenario_solver_*.json files."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print docker commands without executing them.")
    parser.add_argument("--location", metavar="NAME",
                        help="Restrict to a single Location_* directory.")
    parser.add_argument("--version", choices=PLANNER_DOCKER_IMAGE_VERSIONS.keys(), default="local",
                        help="Pick a docker image version.")
    parser.add_argument("--planner", choices=["symbolic", "enhsp"], default="symbolic",
                        help="Planner implementation to use inside the container.")
    args = parser.parse_args()

    locations = [ROOT / args.location] if args.location else sorted(ROOT.glob("Location_*/"))

    total, errors = 0, 0
    for loc in locations:
        if not loc.is_dir():
            print(f"WARNING: {loc} not found, skipping.", file=sys.stderr)
            continue
        scenarios = sorted(loc.glob("scenarios/scenario_solver_*.json"))
        if not scenarios:
            continue
        print(f"\n{loc.name} ({len(scenarios)} scenario(s))")
        for scenario in scenarios:
            total += 1
            if not _run_scenario(PLANNER_DOCKER_IMAGE_VERSIONS[args.version], loc, scenario, args.planner, args.dry_run):
                errors += 1

    print(f"\nDone: {total - errors}/{total} succeeded.")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
