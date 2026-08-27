#!/usr/bin/env python3
"""Run the HIP solver docker image on all scenario_*.json files."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from docker_utils import ensure_docker_running, pull_flag

ROOT = Path(__file__).parent
DOCKER_IMAGE_VERSIONS = {
    "legacy": "ghcr.io/robust-rail-nl/hip:1.4.2",
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


def _plan_name(scenario: Path) -> str:
    suffix = scenario.stem.removeprefix("scenario_")
    return f"plan_{suffix}.json"


def _run_scenario(docker_image: str, location_dir: Path, scenario: Path, dry_run: bool) -> bool:
    plan_name = _plan_name(scenario)
    config_path = location_dir / TEMP_CONFIG
    params = _parse_config(location_dir / "config_solver.yaml")

    cmd = [
        "docker", "run", "--rm",
        *pull_flag(docker_image),
        *(["--user", f"{os.getuid()}:{os.getgid()}"] if sys.platform != "win32" else []),
        "--mount", f"type=bind,source={location_dir.resolve()},target={CONTAINER_DB}",
        docker_image,
        f"--config={CONTAINER_DB}/{TEMP_CONFIG}",
    ]

    print(f"  {scenario.name}  ->  {plan_name}")
    if dry_run:
        print(f"    [dry-run] {' '.join(cmd)}")
        return True

    plans_dir = location_dir / "plans"
    plans_dir.mkdir(exist_ok=True)
    plan_stem = Path(plan_name).stem
    out_file = plans_dir / f"{plan_stem}.out"
    err_file = plans_dir / f"{plan_stem}.err"

    _write_config(config_path, scenario.name, plan_name, params)
    returncode = None
    ok = False
    try:
        with open(out_file, "w") as fout, open(err_file, "w") as ferr:
            result = subprocess.run(cmd, stdout=fout, stderr=ferr)
        returncode = result.returncode
        ok = returncode == 0
    except Exception as exc:
        print(f"    ERROR: {exc}", file=sys.stderr)
    finally:
        config_path.unlink(missing_ok=True)

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
        description="Run the HIP solver on all scenario_*.json files."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print docker commands without executing them.")
    parser.add_argument("--location", metavar="NAME",
                        help="Restrict to a single Location_* directory (e.g. Location_SimpleService).")
    parser.add_argument("--version", choices=DOCKER_IMAGE_VERSIONS.keys(), default='stable',
                        help="Pick a docker image version ('legacy' no longer works against this "
                             "repo's fixtures — Phase 1 moved run_*.py to the unified format "
                             "unconditionally; 'local' is reserved for locally built images; "
                             "'edge' tracks the newest not-yet-vetted push to the edge branch).")
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
            if not _run_scenario(DOCKER_IMAGE_VERSIONS[args.version], loc, scenario, args.dry_run):
                errors += 1

    print(f"\nDone: {total - errors}/{total} succeeded.")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
