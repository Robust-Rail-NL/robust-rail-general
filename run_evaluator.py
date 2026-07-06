#!/usr/bin/env python3
"""Run the TORS evaluator docker image on all plan files that have a matching scenario."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
DOCKER_IMAGE_VERSIONS = {
    "protobuf": "ghcr.io/robust-rail-nl/tors:0.2",
    "pydantic": "ghcr.io/robust-rail-nl/tors:2.0.0-alpha.1",
}
CONTAINER_DB = "/app/database"


def _scenario_name(plan: Path) -> str:
    return plan.stem.removeprefix("plan_")


def _run_plan(docker_image: str, location_dir: Path, plan: Path, dry_run: bool) -> bool:
    name = _scenario_name(plan)
    scenario = location_dir / "scenarios" / f"scenario_{name}.json"

    if not scenario.exists():
        print(f"  SKIP {plan.name}: no matching scenario_{name}.json", file=sys.stderr)
        return True  # not a failure — plan may predate the scenario file

    eval_dir = location_dir / "evaluations"
    eval_dir.mkdir(exist_ok=True)
    eval_file = eval_dir / f"eval_{name}.txt"

    cmd = [
        "docker", "run", "--rm",
        *(["--user", f"{os.getuid()}:{os.getgid()}"] if sys.platform != "win32" else []),
        "--mount", f"type=bind,source={location_dir.resolve()},target={CONTAINER_DB}",
        docker_image,
        "--mode", "EVAL_AND_STORE",
        "--path_location", CONTAINER_DB,
        "--path_scenario", f"{CONTAINER_DB}/scenarios/scenario_{name}.json",
        "--path_plan", f"{CONTAINER_DB}/plans/{plan.name}",
        "--path_eval_result", f"{CONTAINER_DB}/evaluations/eval_{name}.txt",
        "--plan_type", "Solver",
    ]

    print(f"  {plan.name}  ->  evaluations/eval_{name}.txt")
    if dry_run:
        print(f"    [dry-run] {' '.join(cmd)}")
        return True

    returncode = None
    try:
        returncode = subprocess.run(cmd).returncode
        ok = returncode == 0
    except Exception as exc:
        print(f"    ERROR: {exc}", file=sys.stderr)
        ok = False

    if not ok and returncode is not None:
        print(f"    FAILED (exit {returncode})", file=sys.stderr)
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the TORS evaluator on all plans that have a matching scenario."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print docker commands without executing them.")
    parser.add_argument("--location", metavar="NAME",
                        help="Restrict to a single Location_* directory.")
    parser.add_argument("--version", choices=['protobuf', 'pydantic'], default='pydantic',
                        help="Pick a docker image version.")
    args = parser.parse_args()

    locations = [ROOT / args.location] if args.location else sorted(ROOT.glob("Location_*/"))

    total, errors = 0, 0
    for loc in locations:
        if not loc.is_dir():
            print(f"WARNING: {loc} not found, skipping.", file=sys.stderr)
            continue
        plans = sorted(loc.glob("plans/plan_*.json"))
        if not plans:
            continue
        print(f"\n{loc.name} ({len(plans)} plan(s))")
        for plan in plans:
            total += 1
            if not _run_plan(DOCKER_IMAGE_VERSIONS[args.version], loc, plan, args.dry_run):
                errors += 1

    print(f"\nDone: {total - errors}/{total} succeeded.")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
