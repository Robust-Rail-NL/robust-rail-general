#!/usr/bin/env python3
"""Run the generator docker image on all scenario_config_*.json files."""

import argparse
import os
import sys
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
INSTANCE_PREFIX = "scenario_config_"
DOCKER_IMAGE_VERSIONS = {
    "stable": "ghcr.io/robust-rail-nl/generator:latest",
    "stable-assert": "ghcr.io/robust-rail-nl/generator:latest",
    "edge": "ghcr.io/robust-rail-nl/generator:latest",
    "local": "generator:latest",
}
CONTAINER_DB = "/app/database"

def _instance_name(path: Path) -> str:
    return instance_of(path, INSTANCE_PREFIX)

def _run_config(docker_image: str, location_dir: Path, config: Path, dry_run: bool,
                config_dir: Path | None = None) -> bool:
    name = _instance_name(config)
    cname = container_name("generator", name)
    cmd = [
        "docker", "run", "--rm",
        "--name", cname,
        *(["--user", f"{os.getuid()}:{os.getgid()}"] if sys.platform != "win32" else []),
        "--mount", f"type=bind,source={location_dir.resolve()},target={CONTAINER_DB}",
        *(["--mount", f"type=bind,source={config_dir.resolve()},target={CONTAINER_DB}/configurations"]
          if config_dir else []),
        docker_image,
        "--config", config.name,
        "--path", CONTAINER_DB,
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

    returncode, _ = run_container(cmd, cname, out_file, err_file, None)
    ok = returncode == 0

    footer = f"--- exit: {returncode if returncode is not None else 'error'}"
    out_lines, err_lines = finish_capture(out_file, err_file, footer, ok)
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
                             "hand-written configs and the location supplies everything else. "
                             "It overlays the location's own configurations/ rather than merging "
                             "with it, so only this directory's configs are visible.")
    parser.add_argument("--no-pull", action="store_true",
                        help="Skip the up-front 'docker pull'. For a driver like "
                             "run_experiment.py that invokes this script once per attempt and "
                             "pulls each image once itself — without it, every invocation would "
                             "re-check the registry for an image that cannot change mid-run.")
    parser.add_argument("--version", choices=DOCKER_IMAGE_VERSIONS.keys(), default="stable",
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
        available += [_instance_name(c) for c in configs]
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
