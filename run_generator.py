#!/usr/bin/env python3
"""Run the generator docker image on all scenario_config_*.json files."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
DOCKER_IMAGE_VERSIONS = {
    "protobuf": "ghcr.io/robust-rail-nl/generator:1.2.0",
    "pydantic": "ghcr.io/robust-rail-nl/generator:2.0.0-alpha.2",
}
CONTAINER_DB = "/app/database"


def _config_name(config: Path) -> str:
    return config.stem.removeprefix("scenario_config_")


def _run_config(docker_image: str, location_dir: Path, config: Path, dry_run: bool) -> bool:
    name = _config_name(config)
    cmd = [
        "docker", "run", "--rm",
        *(["--user", f"{os.getuid()}:{os.getgid()}"] if sys.platform != "win32" else []),
        "--mount", f"type=bind,source={location_dir.resolve()},target={CONTAINER_DB}",
        docker_image,
        "--config", config.name,
        "--path", CONTAINER_DB,
    ]

    print(f"  {config.name}  ->  scenario_{name}.json")
    if dry_run:
        print(f"    [dry-run] {' '.join(cmd)}")
        return True

    returncode = None
    try:
        returncode = subprocess.run(cmd).returncode
        ok = returncode == 0
    except Exception as exc:
        print(f"    ERROR: {exc}", file=sys.stderr)
        ok = False

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
    parser.add_argument("--version", choices=['protobuf', 'pydantic'], default='pydantic',
                        help="Pick a docker image version.")
    args = parser.parse_args()

    locations = [ROOT / args.location] if args.location else sorted(ROOT.glob("Location_*/"))

    total, errors = 0, 0
    for loc in locations:
        if not loc.is_dir():
            print(f"WARNING: {loc} not found, skipping.", file=sys.stderr)
            continue
        configs = sorted(loc.glob("configurations/scenario_config_*.json"))
        if not configs:
            continue
        print(f"\n{loc.name} ({len(configs)} config(s))")
        for config in configs:
            total += 1
            if not _run_config(DOCKER_IMAGE_VERSIONS[args.version], loc, config, args.dry_run):
                errors += 1

    print(f"\nDone: {total - errors}/{total} succeeded.")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
