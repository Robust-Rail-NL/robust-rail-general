#!/usr/bin/env python3
"""Run the TORS evaluator docker image on all plan files that have a matching scenario."""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from itertools import chain
from pathlib import Path

from scripts.docker_utils import (
    container_name,
    ensure_docker_running,
    ensure_pulled,
    finish_capture,
    run_container,
)
from scripts.instance_filter import fail_no_match, instance_of, select

ROOT = Path(__file__).parent
INSTANCE_PREFIX = "plan_"
DOCKER_IMAGE_VERSIONS = {
    "stable": "ghcr.io/robust-rail-nl/tors:latest",
    "stable-assert": "ghcr.io/robust-rail-nl/tors:assert",
    "edge": "ghcr.io/robust-rail-nl/tors:edge",
    "local": "tors:latest",
}
CONTAINER_DB = "/app/database"

def _instance_name(path: Path) -> str:
    return instance_of(path, INSTANCE_PREFIX)

def _run_plan(docker_image: str, location_dir: Path, plan: Path, dry_run: bool) -> bool:
    name = _instance_name(plan)
    scenario = location_dir / "scenarios" / f"scenario_{name}.json"

    if not scenario.exists():
        print(f"  SKIP {plan.name}: no matching scenario_{name}.json", file=sys.stderr)
        return True

    if not (location_dir / "config.json").exists():
        print(f"  SKIP {plan.name}: {location_dir}/config.json missing — "
              f"required by the evaluator alongside location.json", file=sys.stderr)
        return False

    eval_dir = location_dir / "evaluations"
    eval_dir.mkdir(exist_ok=True)
    out_file = eval_dir / f"eval_{name}.out"
    err_file = eval_dir / f"eval_{name}.err"

    cname = container_name("evaluator", name)
    cmd = [
        "docker", "run", "--rm",
        "--name", cname,
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

    returncode, _ = run_container(cmd, cname, out_file, err_file, None)
    ok = returncode == 0

    footer = f"--- exit: {returncode if returncode is not None else 'error'}"
    out_lines, err_lines = finish_capture(out_file, err_file, footer, ok)
    err_part = f"  stderr: {err_lines}L" if err_lines else ""
    print(f"    stdout: {out_lines}L{err_part}  (exit {returncode})")

    if not ok and returncode is not None:
        print(f"    FAILED (exit {returncode})", file=sys.stderr)
    return ok


def _classify_verdict(out_text: str, err_text: str, txt_text: str) -> tuple[str, str]:
    for line in chain(err_text.splitlines(), out_text.splitlines()):
        if "Issue detected with the Scenario" in line:
            return "rejected", line.split("Scenario:", 1)[-1].strip()
    if "The plan is valid" in out_text:
        return "accepted", ""
    reason = next(
        (
            ln.split("The action is invalid.", 1)[-1].strip().rstrip(".")
            for ln in chain(out_text.splitlines(), txt_text.splitlines())
            if "Scenario failed" in ln
        ),
        None,
    )
    if reason is not None:
        return "rejected", reason
    if txt_text.strip():
        return "rejected", "plan rejected"
    return "error", "evaluator produced no readable verdict"


def _run_plan_single(docker_image: str, location_dir: Path, plan: Path, scenario: Path,
                     version: str, dry_run: bool) -> dict:
    plan = plan.resolve()
    plan_dir = plan.parent
    cname = container_name("evaluator", instance_of(scenario, "scenario_"))

    cmd = [
        "docker", "run", "--rm",
        "--name", cname,
        *(["--user", f"{os.getuid()}:{os.getgid()}"] if sys.platform != "win32" else []),
        "--mount", f"type=bind,source={location_dir.resolve()},target={CONTAINER_DB}",
        "--mount", f"type=bind,source={plan_dir},target=/app/planio",
        docker_image,
        "--mode", "EVAL_AND_STORE",
        "--path_location", CONTAINER_DB,
        "--path_scenario", f"{CONTAINER_DB}/scenarios/{scenario.name}",
        "--path_plan", f"/app/planio/{plan.name}",
        "--path_eval_result", "/app/planio/eval.txt",
        "--plan_type", "Solver",
    ]

    print(f"  {plan}  ->  {plan_dir}/eval_result.json")
    if dry_run:
        print(f"    [dry-run] {' '.join(cmd)}")
        return {}

    out_file, err_file = plan_dir / "eval.out", plan_dir / "eval.err"
    txt_file = plan_dir / "eval.txt"
    start, start_iso = time.monotonic(), datetime.now(timezone.utc).isoformat()
    returncode, _ = run_container(cmd, cname, out_file, err_file, None)

    def _read(path: Path) -> str:
        return path.read_text(errors="replace") if path.exists() else ""

    verdict, reason = _classify_verdict(_read(out_file), _read(err_file), _read(txt_file))
    record = {
        "instance": instance_of(scenario, "scenario_"),
        "location": location_dir.name,
        "scenario": scenario.name,
        "plan": str(plan),
        "version": version,
        "image": docker_image,
        "command": cmd,
        "start_time": start_iso,
        "end_time": datetime.now(timezone.utc).isoformat(),
        "wall_seconds": round(time.monotonic() - start, 3),
        "exit_code": returncode,
        "verdict": verdict,
        "solved": verdict == "accepted",
        "reason": reason,
    }
    (plan_dir / "eval_result.json").write_text(json.dumps(record, indent=2) + "\n")

    print(f"    exit {returncode}  verdict={verdict}  solved={record['solved']}  "
          f"wall={record['wall_seconds']:.1f}s")
    if returncode != 0:
        print(f"    FAILED (exit {returncode})", file=sys.stderr)
    return record


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the TORS evaluator on all plans that have a matching scenario."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print docker commands without executing them.")
    parser.add_argument("--location", metavar="NAME",
                        help="Restrict to a single Location_* directory.")
    parser.add_argument("--instance", metavar="NAME",
                        help="Restrict to a single plans/plan_<NAME>.json (a pasted filename works "
                             "too). Accepts shell-style wildcards; exits non-zero if it matches "
                             "nothing.")
    parser.add_argument("--plan", metavar="FILE", type=Path,
                        help="Evaluate this one plan file wherever it lives — typically a "
                             "plan.json under a run_solver.py/run_planner.py --output-dir. "
                             "eval.out/.err/.txt and eval_result.json are written beside it "
                             "instead of into <location>/evaluations/. Requires --location and "
                             "--instance (to find the matching scenario).")
    parser.add_argument("--no-pull", action="store_true",
                        help="Skip the up-front 'docker pull'. For a driver like "
                             "run_experiment.py that invokes this script once per attempt and "
                             "pulls each image once itself — without it, every invocation would "
                             "re-check the registry for an image that cannot change mid-run.")
    parser.add_argument("--version", choices=DOCKER_IMAGE_VERSIONS.keys(), default="stable",
                        help="Pick a docker image version ('local' is reserved for locally built "
                             "images).")
    args = parser.parse_args()

    if args.plan:
        if not args.location or not args.instance:
            parser.error("--plan requires --location and --instance: the plan lives outside the "
                         "location, so neither the scenario nor the location can be inferred "
                         "from its path.")
        if not args.dry_run and not args.plan.exists():
            parser.error(f"No such plan file: {args.plan}")

    if not args.dry_run:
        ensure_docker_running()
        if not args.no_pull:
            ensure_pulled(DOCKER_IMAGE_VERSIONS[args.version])

    if args.plan:
        loc = ROOT / args.location
        name = args.instance.removesuffix(".json")
        for stray_prefix in ("scenario_", "plan_"):
            name = name.removeprefix(stray_prefix)
        candidates = sorted(loc.glob("scenarios/scenario_*.json"))
        scenarios = select(candidates, name, "scenario_")
        if len(scenarios) == 1:
            scenario = scenarios[0]
        elif scenarios:
            sys.exit(f"ERROR: --instance {args.instance!r} matched {len(scenarios)} scenarios; "
                     f"--plan evaluates one. Narrow it to exactly one.")
        elif args.dry_run:
            scenario = loc / "scenarios" / f"scenario_{name}.json"
        else:
            fail_no_match(args.instance, [instance_of(p, "scenario_") for p in candidates])
        if not args.dry_run and not scenario.exists():
            sys.exit(f"ERROR: no matching scenario for --instance {args.instance!r}: {scenario}")
        record = _run_plan_single(DOCKER_IMAGE_VERSIONS[args.version], loc, args.plan, scenario,
                                  args.version, args.dry_run)
        sys.exit(0 if (not record or record.get("verdict") != "error") else 1)

    locations = [ROOT / args.location] if args.location else sorted(ROOT.glob("Location_*/"))

    total, errors = 0, 0
    available: list[str] = []
    for loc in locations:
        if not loc.is_dir():
            print(f"WARNING: {loc} not found, skipping.", file=sys.stderr)
            continue
        plans = sorted(loc.glob("plans/plan_*.json"))
        available += [_instance_name(p) for p in plans]
        plans = select(plans, args.instance, INSTANCE_PREFIX)
        if not plans:
            continue
        print(f"\n{loc.name} ({len(plans)} plan(s))")
        for plan in plans:
            total += 1
            if not _run_plan(DOCKER_IMAGE_VERSIONS[args.version], loc, plan, args.dry_run):
                errors += 1

    if args.instance and total == 0:
        fail_no_match(args.instance, available)

    print(f"\nDone: {total - errors}/{total} succeeded.")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
