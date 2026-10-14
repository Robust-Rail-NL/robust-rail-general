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
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from scripts.docker_utils import (
    add_engine_args,
    build_run_cmd,
    container_name,
    ensure_pulled,
    ensure_runtime_ready,
    finish_capture,
    run_container,
)
from scripts.instance_filter import fail_no_match, instance_of, select

ROOT = Path(__file__).parent
CONTAINER_DB = "/app/database"
# --scenario only: the directory of a scenario that lives outside the location.
CONTAINER_SCENARIO = "/app/scenario"
INSTANCE_PREFIX = "scenario_"

DEFAULT_PLANNER_TIMEOUT = 600

DOCKER_IMAGE_VERSIONS = {
    "stable": "ghcr.io/robust-rail-nl/planner:latest",
    "stable-assert": "ghcr.io/robust-rail-nl/planner:latest",
    "edge": "ghcr.io/robust-rail-nl/planner:edge",
    "local": "planner:latest",
}
# apptainer-only (see docker_utils.build_run_cmd's workdir param): the
# planner image's own Dockerfile WORKDIR. Its ENTRYPOINT is an absolute path
# (/app/docker-entrypoint.sh), so this isn't needed to find the entrypoint
# itself, but the script it runs may still depend on cwd internally.
CONTAINER_WORKDIR = "/app"
# The image's own Julia depot is read-only to the non-root user the container runs as.
CONTAINER_ENV = {"JULIA_DEPOT_PATH": "/tmp/julia-depot:/opt/julia-depot"}

def _instance_name(path: Path) -> str:
    return instance_of(path, INSTANCE_PREFIX)

def _run_scenario(docker_image: str, location_dir: Path, scenario: Path, planner: str,
                  dry_run: bool, timeout: int, engine: str = "docker",
                  cache_dir: Path | None = None) -> bool:
    name = _instance_name(scenario)
    plan_name = f"plan_{name}.json"
    cname = container_name("planner", name)

    mounts = [(location_dir.resolve(), CONTAINER_DB)]
    args = [
        "--location", f"{CONTAINER_DB}/location.json",
        "--scenario", f"{CONTAINER_DB}/scenarios/{scenario.name}",
        "--planner", planner,
        "--output", f"{CONTAINER_DB}/plans/{plan_name}",
    ]
    cmd = build_run_cmd(engine, docker_image, mounts, args, name=cname, cache_dir=cache_dir,
                        strict=not dry_run, workdir=CONTAINER_WORKDIR, env=CONTAINER_ENV)

    print(f"  {scenario.name}  ->  {plan_name}")
    if dry_run:
        print(f"    [dry-run] {' '.join(cmd)}  (timeout={timeout}s)")
        return True

    plans_dir = location_dir / "plans"
    plans_dir.mkdir(exist_ok=True)
    out_file = plans_dir / f"plan_{name}.out"
    err_file = plans_dir / f"plan_{name}.err"

    returncode, timed_out = run_container(cmd, cname, out_file, err_file, timeout, engine)
    ok = returncode == 0

    footer = (f"--- timeout: killed after {timeout}s (container {cname})" if timed_out
              else f"--- exit: {returncode if returncode is not None else 'error'}")
    out_lines, err_lines = finish_capture(out_file, err_file, footer, ok)
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
                         timeout: int | None = None, engine: str = "docker",
                         cache_dir: Path | None = None, outside_location: bool = False) -> dict:
    """Plan one scenario into output_dir.

    outside_location (--scenario): the scenario file is mounted from wherever it
    lives rather than read from <location>/scenarios/.
    """
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    cname = container_name("planner", _instance_name(scenario))

    mounts = [(location_dir.resolve(), CONTAINER_DB), (output_dir, "/app/output")]
    if outside_location:
        mounts.append((scenario.parent.resolve(), CONTAINER_SCENARIO))
        scenario_container_path = f"{CONTAINER_SCENARIO}/{scenario.name}"
    else:
        scenario_container_path = f"{CONTAINER_DB}/scenarios/{scenario.name}"
    args = [
        "--location", f"{CONTAINER_DB}/location.json",
        "--scenario", scenario_container_path,
        "--planner", planner,
        "--output", "/app/output/plan.json",
    ]
    cmd = build_run_cmd(engine, docker_image, mounts, args, name=cname, cache_dir=cache_dir,
                        strict=not dry_run, workdir=CONTAINER_WORKDIR, env=CONTAINER_ENV)

    plan_path = output_dir / "plan.json"
    print(f"  {scenario.name}  ->  {plan_path}")
    if dry_run:
        print(f"    [dry-run] {' '.join(cmd)}  (timeout={timeout}s)")
        return {}

    out_file, err_file = output_dir / "planner.out", output_dir / "planner.err"
    start, start_iso = time.monotonic(), datetime.now(timezone.utc).isoformat()
    returncode, timed_out = run_container(cmd, cname, out_file, err_file, timeout, engine)

    plan_produced = plan_path.exists() and plan_path.stat().st_size > 0
    record = {
        "instance": _instance_name(scenario),
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
                             "run_experiment.py that invokes this script once per attempt and "
                             "pulls each image once itself — without it, every invocation would "
                             "re-check the registry for an image that cannot change mid-run.")
    parser.add_argument("--version", choices=DOCKER_IMAGE_VERSIONS.keys(), default="stable",
                        help="Pick a docker image version ('local' is reserved for locally built "
                             "images; 'edge' tracks the newest not-yet-vetted push to the edge "
                             "branch).")
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
    parser.add_argument("--scenario", metavar="FILE", type=Path,
                        help="Plan this one scenario_<NAME>.json wherever it lives, instead of "
                             "looking it up in <location>/scenarios/ (requires --location, for "
                             "location.json, and --output-dir). This is how run_experiment.py "
                             "plans the scenarios it keeps under results/<name>/<instance>/.")
    parser.add_argument("--timeout", "--max-duration", type=int, dest="timeout",
                        default=DEFAULT_PLANNER_TIMEOUT, metavar="SECONDS",
                        help=f"Kill a single scenario's planner container after this many "
                             f"seconds (default: {DEFAULT_PLANNER_TIMEOUT}). Guards against a "
                             f"search that never converges; every fixture-scale instance that "
                             f"has actually solved here finished in well under a minute. "
                             f"run_solver.py takes the same flag, so both can be held to one "
                             f"wall-clock budget; --max-duration is kept as an alias so "
                             f"run_experiment.py can pass one flag name to both tools.")
    add_engine_args(parser)
    args = parser.parse_args()

    if args.scenario:
        if args.instance:
            parser.error("--scenario and --instance are mutually exclusive.")
        if not args.location or not args.output_dir:
            parser.error("--scenario requires --location and --output-dir.")
        if not args.dry_run and not args.scenario.is_file():
            parser.error(f"No such scenario file: {args.scenario}")
    elif args.output_dir and not args.instance:
        parser.error("--output-dir requires --instance: it holds one attempt's plan.json and "
                     "result.json, so it must name a single scenario.")

    if not args.dry_run:
        ensure_runtime_ready(args.engine)
        if args.engine == "docker" and not args.no_pull:
            ensure_pulled(DOCKER_IMAGE_VERSIONS[args.version])

    if args.scenario:
        record = _run_scenario_single(DOCKER_IMAGE_VERSIONS[args.version], ROOT / args.location,
                                      args.scenario, args.planner, args.output_dir, args.version,
                                      args.dry_run, args.timeout, args.engine, args.sif_cache_dir,
                                      outside_location=True)
        sys.exit(1 if record and not record.get("plan_produced") else 0)

    locations = [ROOT / args.location] if args.location else sorted(ROOT.glob("Location_*/"))

    total, errors = 0, 0
    available: list[str] = []
    for loc in locations:
        if not loc.is_dir():
            print(f"WARNING: {loc} not found, skipping.", file=sys.stderr)
            continue
        scenarios = sorted(loc.glob("scenarios/scenario_*.json"))
        available += [_instance_name(s) for s in scenarios]
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
                                          args.dry_run, args.timeout, args.engine, args.sif_cache_dir)
            if record and not record.get("plan_produced"):
                errors += 1
            continue
        print(f"\n{loc.name} ({len(scenarios)} scenario(s))")
        for scenario in scenarios:
            total += 1
            if not _run_scenario(DOCKER_IMAGE_VERSIONS[args.version], loc, scenario,
                                 args.planner, args.dry_run, args.timeout, args.engine,
                                 args.sif_cache_dir):
                errors += 1

    if args.instance and total == 0:
        fail_no_match(args.instance, available)

    if total == 0:
        print("WARNING: no scenarios/scenario_*.json found — nothing was planned.",
              file=sys.stderr)

    print(f"\nDone: {total - errors}/{total} succeeded.")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
