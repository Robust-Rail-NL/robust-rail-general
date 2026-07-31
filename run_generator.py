#!/usr/bin/env python3
"""Run the generator docker image on all scenario_config_*.json files."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
DOCKER_IMAGE_VERSIONS = {
    "protobuf": "ghcr.io/robust-rail-nl/generator:1.2.2",
    "pydantic": "ghcr.io/robust-rail-nl/generator:2.0.0-alpha.3",
    "local": "generator:latest",
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
    parser.add_argument("--version", choices=DOCKER_IMAGE_VERSIONS.keys(), default='protobuf',
                        help="Pick a docker image version ('local' is reserved for locally built images).")
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
