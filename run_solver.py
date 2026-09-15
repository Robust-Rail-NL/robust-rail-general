#!/usr/bin/env python3
"""Run the HIP solver docker image on all scenario_*.json files."""

import argparse
import os
import sys
from pathlib import Path

from scripts.docker_utils import container_name, ensure_docker_running, ensure_pulled, run_container
from scripts.instance_filter import fail_no_match, instance_of, select

ROOT = Path(__file__).parent
INSTANCE_PREFIX = "scenario_"
DOCKER_IMAGE_VERSIONS = {
    # Floats forward across ordinary releases rather than pinning one:
    # docker-push.sh only tags :latest on a real X.Y.Z build, so this needs no
    # update here when a new stable version ships. The --version key names a
    # pipeline configuration rather than a literal version number.
    "stable": "ghcr.io/robust-rail-nl/hip:latest",
    # Deliberately the plain image, not an -assert one. The solver is a
    # wall-clock-bounded local search, so an assertions-enabled build explores
    # less of the neighbourhood in the same budget and returns different plans
    # on any scenario that does not converge first — which would break the
    # comparison against the stable baseline. Run the -assert solver image
    # separately as a soak test (seed sweeps looking for a violation) instead.
    "stable-assert": "ghcr.io/robust-rail-nl/hip:latest",
    # Newest push to the edge branch: fixes worth running before they've gone
    # through PR review into main, not yet vetted enough to call stable.
    # Floating tag, always overwritten — see docker-push.sh in
    # robust-rail-solver.
    "edge": "ghcr.io/robust-rail-nl/hip:edge",
    "local": "hip:latest",
}
CONTAINER_DB = "/app/database"
TEMP_CONFIG = "config_solver_run.yaml"


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


def _write_config(config_path: Path, scenario_name: str, plan_name: str, params: dict) -> None:
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
        f'PlanPath: "{CONTAINER_DB}/plans/{plan_name}"\n'
        f'Seed: {params.get("Seed", 1)}\n'
        f'DebugLevel: {params.get("DebugLevel", 0)}\n'
        f'\n'
        f'TabuSearch:\n{_fmt_section(tabu)}\n'
        f'\n'
        f'SimulatedAnnealing:\n{_fmt_section(sa)}\n'
    )
    config_path.write_text(content)


def _scenario_name(scenario: Path) -> str:
    return instance_of(scenario, INSTANCE_PREFIX)


def _plan_name(scenario: Path) -> str:
    return f"plan_{_scenario_name(scenario)}.json"


def _run_scenario(docker_image: str, location_dir: Path, scenario: Path, dry_run: bool,
                  timeout: int | None) -> bool:
    plan_name = _plan_name(scenario)
    config_path = location_dir / TEMP_CONFIG
    params = _parse_config(location_dir / "config_solver.yaml")
    cname = container_name("solver", _scenario_name(scenario))

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

    _write_config(config_path, scenario.name, plan_name, params)
    try:
        returncode, timed_out = run_container(cmd, cname, out_file, err_file, timeout)
    finally:
        config_path.unlink(missing_ok=True)
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
        # SIGKILL, so whatever the search had found is lost: HIP writes its plan
        # at the end of the run, not incrementally. A timed-out solver therefore
        # leaves no new plan — and any plan_<suffix>.json from an earlier run
        # stays on disk for run_evaluator.py to pick up. See --timeout's help.
        print(f"    TIMEOUT after {timeout}s, container killed", file=sys.stderr)
    elif not ok and returncode is not None:
        print(f"    FAILED (exit {returncode})", file=sys.stderr)
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the HIP solver on all scenario_*.json files."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print docker commands without executing them.")
    parser.add_argument("--location", metavar="NAME",
                        help="Restrict to a single Location_* directory (e.g. Location_SimpleService).")
    parser.add_argument("--instance", metavar="NAME",
                        help="Restrict to a single scenarios/scenario_<NAME>.json (a pasted "
                             "filename works too). Accepts shell-style wildcards; exits non-zero "
                             "if it matches nothing.")
    parser.add_argument("--timeout", type=int, default=None, metavar="SECONDS",
                        help="Kill a single scenario's solver container after this many seconds. "
                             "Off by default, because the solver already bounds itself with "
                             "SimulatedAnnealing.MaxDuration in config_solver.yaml and exits "
                             "cleanly there, writing its best plan; this kill is a SIGKILL and "
                             "forfeits that plan. Set it equal to run_planner.py's --timeout, and "
                             "MaxDuration above it, to hold both tools to one externally-enforced "
                             "wall-clock budget for a like-for-like comparison.")
    parser.add_argument("--version", choices=DOCKER_IMAGE_VERSIONS.keys(), default='stable',
                        help="Pick a docker image version ('local' is reserved for locally built "
                             "images; " "'edge' tracks the newest not-yet-vetted push to the edge "
                             "branch).")
    args = parser.parse_args()

    if not args.dry_run:
        ensure_docker_running()
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
        print(f"\n{loc.name} ({len(scenarios)} scenario(s))")
        for scenario in scenarios:
            total += 1
            if not _run_scenario(DOCKER_IMAGE_VERSIONS[args.version], loc, scenario, args.dry_run,
                                 args.timeout):
                errors += 1

    if args.instance and total == 0:
        fail_no_match(args.instance, available)

    print(f"\nDone: {total - errors}/{total} succeeded.")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
