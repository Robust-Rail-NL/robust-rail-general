#!/usr/bin/env python3
"""Run the TORS evaluator docker image on all plan files that have a matching scenario."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from docker_utils import ensure_docker_running

ROOT = Path(__file__).parent
DOCKER_IMAGE_VERSIONS = {
    "legacy": "ghcr.io/robust-rail-nl/tors:1.3.1",
    "2.0.0": "ghcr.io/robust-rail-nl/tors:2.0.0-rc.2",
    # The evaluator is the oracle the pipeline trusts, and its assertions build
    # produces byte-identical output to the plain one (verified across all
    # KleineBinckhorst scenarios) while turning an internal invariant violation
    # into an abort rather than a verdict computed from corrupt state. A run
    # that trips one exits 134/139 with the assertion text in the .err file,
    # which reads very differently from an ordinary "plan is not valid".
    "2.0.0-assert": "ghcr.io/robust-rail-nl/tors:2.0.0-rc.2-assert",
    "local": "tors:latest",
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
    out_file = eval_dir / f"eval_{name}.out"
    err_file = eval_dir / f"eval_{name}.err"

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
        description="Run the TORS evaluator on all plans that have a matching scenario."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print docker commands without executing them.")
    parser.add_argument("--location", metavar="NAME",
                        help="Restrict to a single Location_* directory.")
    parser.add_argument("--version", choices=DOCKER_IMAGE_VERSIONS.keys(), default='2.0.0',
                        help="Pick a docker image version ('legacy' no longer works against this "
                             "repo's fixtures — Phase 1 moved run_*.py to the unified format "
                             "unconditionally; 'local' is reserved for locally built images).")
    args = parser.parse_args()

    if not args.dry_run:
        ensure_docker_running()

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
