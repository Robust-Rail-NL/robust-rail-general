#!/usr/bin/env python3
"""Run the HIP solver docker image on all scenario_*.json files."""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
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
INSTANCE_PREFIX = "scenario_"
DOCKER_IMAGE_VERSIONS = {
    "stable": "ghcr.io/robust-rail-nl/hip:latest",
    "stable-assert": "ghcr.io/robust-rail-nl/hip:latest",
    "edge": "ghcr.io/robust-rail-nl/hip:edge",
    "local": "hip:latest",
}
CONTAINER_DB = "/app/database"
CONTAINER_OUT = "/app/output"
TEMP_CONFIG = "config_solver_run.yaml"

BACKSTOP_GRACE = 120


def _parse_config(config_path: Path) -> dict:
    """Parse the solver YAML config without an external library."""
    config: dict = {}
    current_section: str | None = None
    with open(config_path) as f:
        for line in f:
            line = line.rstrip()
            if not line or line.startswith("#"):
                continue
            if line[0] in (" ", "\t"):
                if current_section is not None and ":" in line:
                    k, _, v = line.strip().partition(":")
                    v = v.strip().strip('"')
                    try:
                        v = int(v) if "." not in v else float(v)
                    except (ValueError, TypeError):
                        pass
                    config[current_section][k.strip()] = v
            else:
                current_section = None
                if ":" in line:
                    k, _, v = line.partition(":")
                    k = k.strip()
                    v = v.strip().strip('"')
                    if not v:
                        current_section = k
                        config[k] = {}
                    else:
                        try:
                            v = int(v) if "." not in v else float(v)
                        except (ValueError, TypeError):
                            pass
                        config[k] = v
    return config


def _fmt_section(d: dict, indent: int = 2) -> str:
    pad = " " * indent
    return "\n".join(f"{pad}{k}: {v}" for k, v in d.items())


def _write_config(config_path: Path, scenario_name: str, plan_container_path: str,
                  params: dict) -> None:
    tabu = params.get("TabuSearch", {
        "Iterations": 40, "IterationsUntilReset": 100, "TabuListLength": 16, "Bias": 0.5,
    })
    sa = params.get("SimulatedAnnealing", {
        "MaxDuration": 3600, "StopWhenFeasible": "true", "IterationsUntilReset": 15000,
        "T": 15, "A": 0.97, "Q": 2000, "Reset": 2000, "Bias": 0.2,
        "IntensifyOnImprovement": "false",
    })
    content = (
        f'LocationPath: "{CONTAINER_DB}/location.json"\n'
        f'ScenarioPath: "{CONTAINER_DB}/scenarios/{scenario_name}"\n'
        f'PlanPath: "{plan_container_path}"\n'
        f'Seed: {params.get("Seed", 1)}\n'
        f'DebugLevel: {params.get("DebugLevel", 0)}\n'
        f'\n'
        f'TabuSearch:\n{_fmt_section(tabu)}\n'
        f'\n'
        f'SimulatedAnnealing:\n{_fmt_section(sa)}\n'
    )
    config_path.write_text(content)


def _backstop(max_duration: int | None) -> int | None:
    """The external-kill deadline implied by an internal budget, if any."""
    return None if max_duration is None else max_duration + BACKSTOP_GRACE


def _apply_overrides(params: dict, max_duration: int | None, seed: int | None) -> dict:
    """Fold --max-duration/--seed into the parsed config_solver.yaml params.

    Applied on both the batch and the single-instance path, so neither flag is
    a silent no-op depending on which one you happen to be on.
    """
    if seed is not None:
        params["Seed"] = seed
    if max_duration is not None:
        params.setdefault("SimulatedAnnealing", {})["MaxDuration"] = max_duration
    return params


def _instance_name(path: Path) -> str:
    return instance_of(path, INSTANCE_PREFIX)


def _plan_name(scenario: Path) -> str:
    return f"plan_{_instance_name(scenario)}.json"


def _run_scenario(docker_image: str, location_dir: Path, scenario: Path, dry_run: bool,
                  timeout: int | None, max_duration: int | None = None,
                  seed: int | None = None) -> bool:
    plan_name = _plan_name(scenario)
    config_path = location_dir / TEMP_CONFIG
    params = _apply_overrides(_parse_config(location_dir / "config_solver.yaml"),
                              max_duration, seed)
    cname = container_name("solver", _instance_name(scenario))

    cmd = [
        "docker", "run", "--rm",
        "--name", cname,
        *(["--user", f"{os.getuid()}:{os.getgid()}"] if sys.platform != "win32" else []),
        "--mount", f"type=bind,source={location_dir.resolve()},target={CONTAINER_DB}",
        docker_image,
        f"--config={CONTAINER_DB}/{TEMP_CONFIG}",
    ]

    print(f"  {scenario.name}  ->  {plan_name}")
    if dry_run:
        budget = f"  (timeout={timeout}s)" if timeout else ""
        print(f"    [dry-run] {' '.join(cmd)}{budget}")
        return True

    plans_dir = location_dir / "plans"
    plans_dir.mkdir(exist_ok=True)
    plan_stem = Path(plan_name).stem
    out_file = plans_dir / f"{plan_stem}.out"
    err_file = plans_dir / f"{plan_stem}.err"

    _write_config(config_path, scenario.name, f"{CONTAINER_DB}/plans/{plan_name}", params)
    try:
        returncode, timed_out = run_container(cmd, cname, out_file, err_file, timeout)
    finally:
        config_path.unlink(missing_ok=True)
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


def _run_scenario_single(docker_image: str, location_dir: Path, scenario: Path, output_dir: Path,
                         version: str, dry_run: bool, max_duration: int | None = None,
                         seed: int | None = None, timeout: int | None = None) -> dict:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    config_path = output_dir / TEMP_CONFIG
    params = _apply_overrides(_parse_config(location_dir / "config_solver.yaml"),
                              max_duration, seed)
    seed_used = params.get("Seed", 1)
    cname = container_name("solver", _instance_name(scenario))

    cmd = [
        "docker", "run", "--rm", "--name", cname,
        *(["--user", f"{os.getuid()}:{os.getgid()}"] if sys.platform != "win32" else []),
        "--mount", f"type=bind,source={location_dir.resolve()},target={CONTAINER_DB}",
        "--mount", f"type=bind,source={output_dir},target={CONTAINER_OUT}",
        docker_image,
        f"--config={CONTAINER_OUT}/{config_path.name}",
    ]

    plan_path = output_dir / "plan.json"
    print(f"  {scenario.name}  ->  {plan_path}")
    if dry_run:
        print(f"    [dry-run] {' '.join(cmd)}")
        return {}

    _write_config(config_path, scenario.name, f"{CONTAINER_OUT}/plan.json", params)
    out_file, err_file = output_dir / "solver.out", output_dir / "solver.err"
    start, start_iso = time.monotonic(), datetime.now(timezone.utc).isoformat()
    returncode, timed_out = run_container(cmd, cname, out_file, err_file,
                                          timeout or _backstop(max_duration))

    plan_produced = plan_path.exists() and plan_path.stat().st_size > 0
    record = {
        "instance": _instance_name(scenario),
        "tool": "solver",
        "location": location_dir.name,
        "scenario": scenario.name,
        "version": version,
        "image": docker_image,
        "command": cmd,
        "max_duration": max_duration,
        "seed": seed_used,
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
        print(f"    TIMEOUT (container killed past its {max_duration}s budget)", file=sys.stderr)
    elif returncode != 0:
        print(f"    FAILED (exit {returncode})", file=sys.stderr)
    return record


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the HIP solver on all scenario_*.json files."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print docker commands without executing them.")
    parser.add_argument("--location", metavar="NAME",
                        help="Restrict to a single Location_* directory.")
    parser.add_argument("--instance", metavar="NAME",
                        help="Restrict to a single scenarios/scenario_<NAME>.json (a pasted "
                             "filename works too). Accepts shell-style wildcards; exits non-zero "
                             "if it matches nothing.")
    parser.add_argument("--output-dir", metavar="DIR", type=Path,
                        help="Write plan.json, solver.out/.err and result.json here instead of "
                             "into <location>/plans/ (requires --instance to name a single "
                             "scenario). This is the per-attempt layout run_experiment.py drives, "
                             "keeping each (instance, tool) run in its own directory rather than "
                             "the shared, filename-keyed plans/ folder.")
    parser.add_argument("--max-duration", type=int, metavar="SECONDS",
                        help="Override SimulatedAnnealing.MaxDuration for this run — the solver's "
                             "own budget, which it stops at cleanly and still writes its best plan "
                             f"from. An external kill is armed {BACKSTOP_GRACE}s above it as a "
                             "backstop for a wedged container. Prefer this over --timeout for "
                             "solver-vs-planner comparison: a SIGKILL at the budget would forfeit "
                             "the plan an anytime search had already found.")
    parser.add_argument("--seed", type=int, metavar="N",
                        help="Override the solver's Seed for this run (default: whatever "
                             "config_solver.yaml says, falling back to 1).")
    parser.add_argument("--timeout", type=int, default=None, metavar="SECONDS",
                        help="Kill a single scenario's solver container after this many seconds. "
                             "Off by default, because the solver already bounds itself with "
                             "SimulatedAnnealing.MaxDuration and exits cleanly there, writing its "
                             "best plan; this kill is a SIGKILL and forfeits that plan. Set it "
                             "equal to run_planner.py's --timeout, and MaxDuration above it, to "
                             "hold both tools to one externally-enforced budget.")
    parser.add_argument("--no-pull", action="store_true",
                        help="Skip the up-front 'docker pull'. For a driver like "
                             "run_experiment.py that invokes this script once per attempt and "
                             "pulls each image once itself — without it, every invocation would "
                             "re-check the registry for an image that cannot change mid-run.")
    parser.add_argument("--version", choices=DOCKER_IMAGE_VERSIONS.keys(), default="stable",
                        help="Pick a docker image version ('local' is reserved for locally built "
                             "images; 'edge' tracks the newest not-yet-vetted push to the edge "
                             "branch).")
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
                                          args.output_dir, args.version, args.dry_run,
                                          args.max_duration, args.seed, args.timeout)
            if record and not record.get("plan_produced"):
                errors += 1
            continue
        print(f"\n{loc.name} ({len(scenarios)} scenario(s))")
        for scenario in scenarios:
            total += 1
            if not _run_scenario(DOCKER_IMAGE_VERSIONS[args.version], loc, scenario, args.dry_run,
                                 args.timeout or _backstop(args.max_duration),
                                 args.max_duration, args.seed):
                errors += 1

    if args.instance and total == 0:
        fail_no_match(args.instance, available)

    print(f"\nDone: {total - errors}/{total} succeeded.")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
