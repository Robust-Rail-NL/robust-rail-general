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
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from scripts.docker_utils import container_name, ensure_docker_running, ensure_pulled, run_container
from scripts.instance_filter import fail_no_match, instance_of, select

ROOT = Path(__file__).parent
CONTAINER_DB = "/app/database"
INSTANCE_PREFIX = "scenario_"

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
# - "stable-assert" likewise: the assertions builds are the evaluator's and
#   the solver's. This image has no such variant, so the selector resolves to
#   the plain image and the run stays comparable.
# - "edge": newest push to the planner's own edge branch, not yet vetted
#   enough to call stable. Floating tag, always overwritten — see
#   docker-push-edge.sh in robust-rail-planner, same model as the solver's
#   and evaluator's edge channels (see run_solver.py).
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
    "stable": "ghcr.io/robust-rail-nl/planner:latest",
    "stable-assert": "ghcr.io/robust-rail-nl/planner:latest",
    "edge": "ghcr.io/robust-rail-nl/planner:edge",
    "local": "planner:latest",
}


def _scenario_name(scenario: Path) -> str:
    return instance_of(scenario, INSTANCE_PREFIX)


def _run_scenario(docker_image: str, location_dir: Path, scenario: Path, planner: str, dry_run: bool,
                   timeout: int) -> bool:
    name = _scenario_name(scenario)
    plan_name = f"plan_{name}.json"
    cname = container_name("planner", name)

    cmd = [
        "docker", "run", "--rm",
        "--name", cname,
        *(["--user", f"{os.getuid()}:{os.getgid()}"] if sys.platform != "win32" else []),
        "--env", "JULIA_DEPOT_PATH=/tmp/julia-depot:/opt/julia-depot",
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

    returncode, timed_out = run_container(cmd, cname, out_file, err_file, timeout)
    ok = returncode == 0

    with open(err_file, "a") as f:
        if timed_out:
            f.write(f"--- timeout: killed after {timeout}s (container {cname})\n")
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


def _run_scenario_single(docker_image: str, location_dir: Path, scenario: Path, planner: str,
                         output_dir: Path, version: str, dry_run: bool,
                         timeout: int | None = None) -> dict:
    """Run one scenario into output_dir, and return/record what happened.

    Mirrors run_solver.py's --output-dir mode so the two tools' single-instance
    output is laid out identically for a solver-vs-planner comparison: the same
    plan.json, the same result.json keys, differing only in <tool>.out/.err.

    There is no --max-duration counterpart here. ENHSP's own -timeout option is
    dead code on the enhsp-20 branch this image builds from (parsed into a
    private field, never read — the search dispatch drops it), so an external
    kill is the only budget the planner can actually be held to. The asymmetry
    is real and worth remembering when reading a comparison: the solver stops
    at its budget and still writes its best plan, while the planner is killed
    and writes nothing.
    """
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    cname = container_name("planner", _scenario_name(scenario))

    cmd = [
        "docker", "run", "--rm", "--name", cname,
        *(["--user", f"{os.getuid()}:{os.getgid()}"] if sys.platform != "win32" else []),
        # See the matching comment in _run_scenario: without this, Julia's
        # precompile-cache write into the image's root-owned JULIA_DEPOT_PATH
        # fails with EACCES under --user, for any --planner value.
        "--env", "JULIA_DEPOT_PATH=/tmp/julia-depot:/opt/julia-depot",
        "--mount", f"type=bind,source={location_dir.resolve()},target={CONTAINER_DB}",
        "--mount", f"type=bind,source={output_dir},target=/app/output",
        docker_image,
        "--location", f"{CONTAINER_DB}/location.json",
        "--scenario", f"{CONTAINER_DB}/scenarios/{scenario.name}",
        "--planner", planner,
        "--output", "/app/output/plan.json",
    ]

    plan_path = output_dir / "plan.json"
    print(f"  {scenario.name}  ->  {plan_path}")
    if dry_run:
        print(f"    [dry-run] {' '.join(cmd)}  (timeout={timeout}s)")
        return {}

    out_file, err_file = output_dir / "planner.out", output_dir / "planner.err"
    start, start_iso = time.monotonic(), datetime.now(timezone.utc).isoformat()
    returncode, timed_out = run_container(cmd, cname, out_file, err_file, timeout)

    plan_produced = plan_path.exists() and plan_path.stat().st_size > 0
    record = {
        "instance": _scenario_name(scenario),
        "tool": "planner",
        "planner_impl": planner,
        "location": location_dir.name,
        "scenario": scenario.name,
        "version": version,
        "image": docker_image,
        "command": cmd,
        "max_duration": timeout,
        "start_time": start_iso,
        "end_time": datetime.now(timezone.utc).isoformat(),
        "wall_seconds": round(time.monotonic() - start, 3),
        "exit_code": returncode,
        "timed_out": timed_out,
        "plan_produced": plan_produced,
    }
    (output_dir / "result.json").write_text(json.dumps(record, indent=2) + "\n")

    print(f"    exit {returncode}  timed_out={timed_out}  plan_produced={plan_produced}  "
          f"wall={record['wall_seconds']:.1f}s")
    if timed_out:
        print(f"    TIMEOUT after {timeout}s, container killed", file=sys.stderr)
    elif returncode != 0:
        print(f"    FAILED (exit {returncode})", file=sys.stderr)
    return record


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the planner on all scenario_*.json files."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print docker commands without executing them.")
    parser.add_argument("--location", metavar="NAME",
                        help="Restrict to a single Location_* directory.")
    parser.add_argument("--instance", metavar="NAME",
                        help="Restrict to a single scenarios/scenario_<NAME>.json (a pasted "
                             "filename works too). Accepts shell-style wildcards; exits non-zero "
                             "if it matches nothing.")
    parser.add_argument("--no-pull", action="store_true",
                        help="Skip the up-front 'docker pull'. For a driver like "
                             "run_experiment.py that invokes this script once per attempt: it "
                             "pulls each image once itself, and without this every invocation "
                             "would re-check the registry -- hundreds of round-trips for an "
                             "image that cannot change mid-run, and hundreds of chances for a "
                             "flaky registry to abort the sweep.")
    parser.add_argument("--version", choices=DOCKER_IMAGE_VERSIONS.keys(), default="local",
                        help="Pick a docker image version.")
    parser.add_argument("--planner", choices=["symbolic", "symbolic-rail", "enhsp"],
                        default="symbolic-rail",
                        help="Planner implementation to use inside the container. 'symbolic-rail' "
                             "is the same Julia script as 'symbolic' but with the rail-specific "
                             "heuristic mode (see plan/symbolic_planner.jl in robust-rail-planner).")
    parser.add_argument("--output-dir", metavar="DIR", type=Path,
                        help="Write plan.json, planner.out/.err and result.json here instead of "
                             "into <location>/plans/ (requires --instance to name a single "
                             "scenario). Same per-attempt layout run_solver.py --output-dir "
                             "produces, which is what run_experiment.py drives.")
    # --max-duration is an alias, not a second budget concept: unlike the
    # solver, there is no separate graceful-stop mode here to alias away from
    # (ENHSP's own -timeout is dead code on the branch this image builds
    # from), so both names drive the same external kill. One add_argument
    # call for both means one default and no dest collision to work around.
    parser.add_argument("--timeout", "--max-duration", type=int, dest="timeout",
                        default=DEFAULT_PLANNER_TIMEOUT, metavar="SECONDS",
                        help=f"Kill a single scenario's planner container after this many "
                             f"seconds (default: {DEFAULT_PLANNER_TIMEOUT}). Guards against a "
                             f"search that never converges; every fixture-scale instance that "
                             f"has ever actually solved on this repo's locations finished in "
                             f"well under a minute. run_solver.py takes the same flag, so both "
                             f"can be held to one wall-clock budget for a like-for-like "
                             f"comparison; --max-duration is kept as an alias so "
                             f"run_experiment.py can pass one flag name to both tools.")
    args = parser.parse_args()

    if args.output_dir and not args.instance:
        parser.error("--output-dir requires --instance: it holds one attempt's plan.json and "
                     "result.json, so it must name a single scenario.")

    if not args.dry_run:
        ensure_docker_running()
        if not args.no_pull:
            ensure_pulled(DOCKER_IMAGE_VERSIONS[args.version])

    locations = [ROOT / args.location] if args.location else sorted(ROOT.glob("Location_*/"))

    total, errors = 0, 0
    available: list[str] = []
    for loc in locations:
        if not loc.is_dir():
            print(f"WARNING: {loc} not found, skipping.", file=sys.stderr)
            continue
        scenarios = sorted(loc.glob("scenarios/scenario_*.json"))
        available += [_scenario_name(s) for s in scenarios]
        scenarios = select(scenarios, args.instance, INSTANCE_PREFIX)
        if not scenarios:
            continue
        if args.output_dir:
            if len(scenarios) > 1:
                sys.exit(f"ERROR: --instance {args.instance!r} matched {len(scenarios)} scenarios; "
                         f"--output-dir holds one attempt. Narrow it to exactly one.")
            total += 1
            record = _run_scenario_single(DOCKER_IMAGE_VERSIONS[args.version], loc, scenarios[0],
                                          args.planner, args.output_dir, args.version,
                                          args.dry_run, args.timeout)
            if record and not record.get("plan_produced"):
                errors += 1
            continue
        print(f"\n{loc.name} ({len(scenarios)} scenario(s))")
        for scenario in scenarios:
            total += 1
            if not _run_scenario(DOCKER_IMAGE_VERSIONS[args.version], loc, scenario, args.planner, args.dry_run,
                                  args.timeout):
                errors += 1

    if args.instance and total == 0:
        # Named-but-absent is its own failure, and a more specific one than the
        # empty sweep below: the scenarios exist, just none under that name.
        fail_no_match(args.instance, available)

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
