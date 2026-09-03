#!/usr/bin/env python3
"""Run the planner docker image on all scenario_*.json files.

An alternative to the HIP solver step, not an addition: it converts each
scenario to PDDL, plans, and converts the result back to TORS JSON at
plans/plan_<suffix>.json — the same output convention run_evaluator.py
consumes, and the same filename run_solver.py writes. Running both against one
location would have them overwrite each other, so run_pipeline.py refuses the
combination.

The image is built and published from ../robust-rail-planner by its
docker-push.sh.
"""

import argparse
import os
import subprocess
import sys
import uuid
from pathlib import Path

from docker_utils import ensure_docker_running, pull_flag

ROOT = Path(__file__).parent
CONTAINER_DB = "/app/database"

# ENHSP either solves or OOMs within ~20s on the largest fixture we have
# (marginal_congestion_s12: 16.7s grounding before the heap runs out), and
# every solved fixture-scale instance finishes in single-digit-to-teens of
# seconds. A run with no bound instead of failing loudly can run for hours: a
# non-fixture stress scenario once searched for 3h40m+ without converging
# (KleineBinckhorst_10t_random_42s_random_distribution2, 2026-08-24) and had
# to be killed by hand. 600s (10 minutes, per the planner team) leaves ~30x
# headroom over anything that has ever actually solved on this location,
# while still cutting off a genuine non-convergence in minutes rather than
# hours.
DEFAULT_PLANNER_TIMEOUT = 600

# Named DOCKER_IMAGE_VERSIONS like every other step's, because run_pipeline.py
# reads that attribute by name to report which images a run will use. It was
# PLANNER_DOCKER_IMAGE_VERSIONS, which made `--steps planner` an AttributeError.
#
# The keys mirror the other steps' --version choices so the pipeline can pass
# --version uniformly, but they do not all mean something here:
#
# - "legacy" has no honest value. The planner step did not exist in 1.x, so
#   there is no 1.x planner image to compare against. It maps to the current
#   one rather than to a tag that was never built.
# - "stable-assert" likewise: the assertions builds are the evaluator's and
#   the solver's. This image has no such variant, so the selector resolves to
#   the plain image and the run stays comparable.
# - "edge" likewise: only the solver has an edge channel. This image has no
#   such variant, so the selector resolves to the plain image and the run
#   stays comparable. See run_solver.py.
#
# The version is robust-rail-planner's own (see its VERSION file), deliberately
# not 2.0.0 — that number belongs to the repos sharing an interchange format.
# 0.2.1 is the first image that plans every location. Neither predecessor is
# worth pinning back to for a comparison run:
#
#   0.1.0  matched no pattern for the corridor model's compiled departure, so it
#          dropped every plan's Exit and the moves leading to it, and reported
#          success. Its plans stop at the last service task and are not solutions.
#   0.2.0  emits whole plans but raises UnboundLocalError on any plan whose
#          departing train never moved — fine on SimpleService, dead on
#          KleineBinckhorst.
DOCKER_IMAGE_VERSIONS = {
    "legacy": "ghcr.io/robust-rail-nl/planner:0.4.0",
    "stable": "ghcr.io/robust-rail-nl/planner:0.4.0",
    "stable-assert": "ghcr.io/robust-rail-nl/planner:0.4.0",
    "edge": "ghcr.io/robust-rail-nl/planner:0.4.0",
    "local": "planner:latest",
}


def _scenario_name(scenario: Path) -> str:
    return scenario.stem.removeprefix("scenario_")


def _run_scenario(docker_image: str, location_dir: Path, scenario: Path, planner: str, dry_run: bool,
                   timeout: int) -> bool:
    name = _scenario_name(scenario)
    plan_name = f"plan_{name}.json"
    # Named so a timeout can target this exact container: subprocess.run's own
    # timeout only kills the local `docker run` client, not the container it
    # started, which keeps running under dockerd regardless. Learned by hand
    # on 2026-08-24 — killing the run_planner.py process left the container
    # running for hours until it was separately `docker kill`ed. The uuid
    # suffix (not just the scenario name) avoids a "name already in use"
    # conflict if a previous run's container of the same name is still being
    # torn down.
    container_name = f"planner-{name}-{uuid.uuid4().hex[:8]}"

    cmd = [
        "docker", "run", "--rm",
        *pull_flag(docker_image),
        "--name", container_name,
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
        print(f"    [dry-run] {' '.join(cmd)}  (timeout={timeout}s)")
        return True

    plans_dir = location_dir / "plans"
    plans_dir.mkdir(exist_ok=True)
    out_file = plans_dir / f"plan_{name}.out"
    err_file = plans_dir / f"plan_{name}.err"

    returncode = None
    ok = False
    timed_out = False
    try:
        with open(out_file, "w") as fout, open(err_file, "w") as ferr:
            result = subprocess.run(cmd, stdout=fout, stderr=ferr, timeout=timeout)
        returncode = result.returncode
        ok = returncode == 0
    except subprocess.TimeoutExpired:
        timed_out = True
        # The docker CLI client is already dead (subprocess.run killed it to
        # raise this); the container it started is not. --rm still applies
        # once it's stopped, so a plain kill is enough — no separate rm.
        subprocess.run(["docker", "kill", container_name],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as exc:
        print(f"    ERROR: {exc}", file=sys.stderr)

    with open(err_file, "a") as f:
        if timed_out:
            f.write(f"--- timeout: killed after {timeout}s (container {container_name})\n")
        else:
            f.write(f"--- exit: {returncode if returncode is not None else 'error'}\n")
    out_lines = len(out_file.read_text().splitlines()) if out_file.exists() else 0
    err_lines = len(err_file.read_text().splitlines()) if err_file.exists() else 0
    if ok and err_lines <= 1:
        err_file.unlink(missing_ok=True)
        err_lines = 0
    err_part = f"  stderr: {err_lines}L" if err_lines else ""
    status = f"TIMEOUT after {timeout}s" if timed_out else f"exit {returncode}"
    print(f"    stdout: {out_lines}L{err_part}  ({status})")

    if timed_out:
        print(f"    TIMEOUT after {timeout}s, container killed", file=sys.stderr)
    elif not ok and returncode is not None:
        print(f"    FAILED (exit {returncode})", file=sys.stderr)
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the planner on all scenario_*.json files."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print docker commands without executing them.")
    parser.add_argument("--location", metavar="NAME",
                        help="Restrict to a single Location_* directory.")
    parser.add_argument("--version", choices=DOCKER_IMAGE_VERSIONS.keys(), default="local",
                        help="Pick a docker image version.")
    parser.add_argument("--planner", choices=["symbolic", "enhsp"], default="enhsp",
                        help="Planner implementation to use inside the container.")
    parser.add_argument("--planner-timeout", type=int, default=DEFAULT_PLANNER_TIMEOUT, metavar="SECONDS",
                        help=f"Kill a single scenario's planner container after this many "
                             f"seconds (default: {DEFAULT_PLANNER_TIMEOUT}). Guards against a "
                             f"search that never converges; every fixture-scale instance that "
                             f"has ever actually solved on this repo's locations finished in "
                             f"well under a minute.")
    args = parser.parse_args()

    if not args.dry_run:
        ensure_docker_running()

    locations = [ROOT / args.location] if args.location else sorted(ROOT.glob("Location_*/"))

    total, errors = 0, 0
    for loc in locations:
        if not loc.is_dir():
            print(f"WARNING: {loc} not found, skipping.", file=sys.stderr)
            continue
        scenarios = sorted(loc.glob("scenarios/scenario_*.json"))
        if not scenarios:
            continue
        print(f"\n{loc.name} ({len(scenarios)} scenario(s))")
        for scenario in scenarios:
            total += 1
            if not _run_scenario(DOCKER_IMAGE_VERSIONS[args.version], loc, scenario, args.planner, args.dry_run,
                                  args.planner_timeout):
                errors += 1

    if total == 0:
        # This script spent the whole scenario-unification period globbing
        # scenario_solver_*.json, a filename that stopped existing, and reported
        # "Done: 0/0 succeeded" with exit 0 every time — indistinguishable from
        # a clean run. Finding no work is nearly always a broken glob or a wrong
        # --location rather than a real empty repo, so say so out loud.
        print("WARNING: no scenarios/scenario_*.json found — nothing was planned.",
              file=sys.stderr)

    print(f"\nDone: {total - errors}/{total} succeeded.")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
