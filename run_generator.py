#!/usr/bin/env python3
"""Run the generator docker image on all scenario_config_*.json files."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from scripts.docker_utils import ensure_docker_running, ensure_pulled
from scripts.instance_filter import fail_no_match, instance_of, select

ROOT = Path(__file__).parent
INSTANCE_PREFIX = "scenario_config_"
DOCKER_IMAGE_VERSIONS = {
    "stable": "ghcr.io/robust-rail-nl/generator:latest",
    # Same image: the generator has no assertions build. "stable-assert" names
    # a pipeline configuration — assert the evaluator, leave everything else
    # alone — rather than a per-tool build flag. See run_evaluator.py.
    "stable-assert": "ghcr.io/robust-rail-nl/generator:latest",
    # Same image again: the generator has no edge channel — the solver,
    # planner and evaluator all do. "edge" names a pipeline configuration —
    # run those from their edge channels, leave the generator on stable —
    # rather than a per-tool build flag. See run_solver.py.
    "edge": "ghcr.io/robust-rail-nl/generator:latest",
    "local": "generator:latest",
}
CONTAINER_DB = "/app/database"


def _config_name(config: Path) -> str:
    return instance_of(config, INSTANCE_PREFIX)


def _run_config(docker_image: str, location_dir: Path, config: Path, dry_run: bool,
                config_dir: Path | None = None) -> bool:
    name = _config_name(config)
    cmd = [
        "docker", "run", "--rm",
        *(["--user", f"{os.getuid()}:{os.getgid()}"] if sys.platform != "win32" else []),
        "--mount", f"type=bind,source={location_dir.resolve()},target={CONTAINER_DB}",
        # A second, more specific mount overlays just the configurations/
        # subpath, so the container sees config_dir's contents there instead of
        # the location's own configurations/ — everything else (location.json,
        # the scenarios/ output dir) still resolves against the real location.
        # An overlay, not a merge: only this directory's configs are visible.
        *(["--mount", f"type=bind,source={config_dir.resolve()},target={CONTAINER_DB}/configurations"]
          if config_dir else []),
        docker_image,
        "--config", config.name,
        "--path", CONTAINER_DB,
        # Name the output explicitly rather than letting the generator derive
        # one. Left to itself, create_scenario_from_config() in
        # robust-rail-generator's src/main.py builds the name out of the
        # location, the train count and either "custom" or the seed, so
        # scenario_config_marginal_congestion.json became
        # scenario_KleineBinckhorst_14t_random_1s_marginal_congestion.json —
        # a rule this repo could only mirror by reimplementing it (seed
        # default included) and re-mirroring it on every generator change.
        # Naming it here instead keeps one suffix across all four steps:
        # scenario_<suffix> -> plan_<suffix> -> eval_<suffix>, so a single
        # --instance value selects the same instance at every step.
        "--scenario-file", f"scenario_{name}.json",
    ]

    print(f"  {config.name}  ->  scenario_{name}.json")
    if dry_run:
        print(f"    [dry-run] {' '.join(cmd)}")
        return True

    scenarios_dir = location_dir / "scenarios"
    scenarios_dir.mkdir(exist_ok=True)
    out_file = scenarios_dir / f"scenario_{name}.out"
    err_file = scenarios_dir / f"scenario_{name}.err"

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
        description="Run the generator on all scenario_config_*.json files."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print docker commands without executing them.")
    parser.add_argument("--location", metavar="NAME",
                        help="Restrict to a single Location_* directory.")
    parser.add_argument("--instance", metavar="NAME",
                        help="Restrict to a single configurations/scenario_config_<NAME>.json "
                             "(a pasted filename works too). Accepts shell-style wildcards; exits "
                             "non-zero if it matches nothing.")
    parser.add_argument("--config-dir", metavar="DIR", type=Path,
                        help="Use scenario_config_*.json files from this directory instead of "
                             "<location>/configurations/ (requires --location). This is how "
                             "custom instance sets are generated: point it at a directory of "
                             "hand-written configs and the location supplies everything else "
                             "(location.json, the scenarios/ output dir). It overlays the "
                             "location's own configurations/ inside the container rather than "
                             "merging with it, so only this directory's configs are visible.")
    parser.add_argument("--no-pull", action="store_true",
                        help="Skip the up-front 'docker pull'. For a driver like "
                             "run_experiment.py that invokes this script once per attempt: it "
                             "pulls each image once itself, and without this every invocation "
                             "would re-check the registry -- hundreds of round-trips for an "
                             "image that cannot change mid-run, and hundreds of chances for a "
                             "flaky registry to abort the sweep.")
    parser.add_argument("--version", choices=DOCKER_IMAGE_VERSIONS.keys(), default='stable',
                        help="Pick a docker image version ('local' is reserved for locally built "
                             "images).")
    args = parser.parse_args()

    if args.config_dir and not args.location:
        parser.error("--config-dir requires --location.")
    if args.config_dir and not args.config_dir.is_dir():
        parser.error(f"No such directory: {args.config_dir}")

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
        if args.config_dir:
            configs = sorted(args.config_dir.glob("scenario_config_*.json"))
            if not configs:
                print(f"WARNING: no scenario_config_*.json found under {args.config_dir}",
                      file=sys.stderr)
        else:
            configs = sorted(loc.glob("configurations/scenario_config_*.json"))
        available += [_config_name(c) for c in configs]
        configs = select(configs, args.instance, INSTANCE_PREFIX)
        if not configs:
            continue
        source = f" [from {args.config_dir}]" if args.config_dir else ""
        print(f"\n{loc.name} ({len(configs)} config(s)){source}")
        for config in configs:
            total += 1
            if not _run_config(DOCKER_IMAGE_VERSIONS[args.version], loc, config, args.dry_run,
                               args.config_dir):
                errors += 1

    if args.instance and total == 0:
        fail_no_match(args.instance, available)

    print(f"\nDone: {total - errors}/{total} succeeded.")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
