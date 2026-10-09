#!/usr/bin/env python3
"""Run the generator docker image on all scenario_config_*.json files.

By default each config comes from <location>/configurations/ (or --config-dir)
and its scenario lands in <location>/scenarios/.

--experiment is the self-contained layout run_experiment.py uses instead: the
experiment JSON's "scenario_config" section is the only config. It is expanded
into one generator config per instance in a temporary directory -- the
generator image takes exactly one train count, matching and seed per run --
which is deleted afterwards, and each scenario is written to
<run-dir>/<instance>/scenario_<instance>.json with its .out/.err beside it. The
location only supplies location.json.
"""

import argparse
import json
import sys
import tempfile
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
from scripts import experiment_spec
from scripts.generate_experiment_configs import scenario_params, sweep_configs
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
# --experiment only: the temporary directory holding the expanded configs, and
# the instance's own directory the scenario is written into.
CONTAINER_CONFIG = "/app/config"
CONTAINER_RUN = "/app/run"
# apptainer-only (see docker_utils.build_run_cmd's workdir param): the
# generator image's own Dockerfile WORKDIR, which its ENTRYPOINT ("python
# src/main.py") is relative to.
CONTAINER_WORKDIR = "/app"

def _instance_name(path: Path) -> str:
    return instance_of(path, INSTANCE_PREFIX)

def _run_config(docker_image: str, location_dir: Path, config: Path, dry_run: bool,
                config_dir: Path | None = None, engine: str = "docker",
                cache_dir: Path | None = None, instance_dir: Path | None = None) -> bool:
    """Generate one config's scenario.

    instance_dir (--experiment): write the scenario and its .out/.err there,
    instead of into <location>/scenarios/.
    """
    name = _instance_name(config)
    cname = container_name("generator", name)
    mounts = [(location_dir.resolve(), CONTAINER_DB)]
    if instance_dir:
        # The generator takes a full path for both --config and --scenario-file,
        # so the location stays mounted for location.json alone.
        mounts += [(config.parent.resolve(), CONTAINER_CONFIG),
                   (instance_dir.resolve(), CONTAINER_RUN)]
        config_arg = f"{CONTAINER_CONFIG}/{config.name}"
        scenario_arg = f"{CONTAINER_RUN}/scenario_{name}.json"
    else:
        # An overlay on just the configurations/ subpath, not a merge: only
        # config_dir's contents are visible there.
        if config_dir:
            mounts.append((config_dir.resolve(), f"{CONTAINER_DB}/configurations"))
        config_arg = config.name
        scenario_arg = f"scenario_{name}.json"
    args = [
        "--config", config_arg,
        "--path", CONTAINER_DB,
        "--scenario-file", scenario_arg,
    ]
    cmd = build_run_cmd(engine, docker_image, mounts, args, name=cname, cache_dir=cache_dir,
                        strict=not dry_run, workdir=CONTAINER_WORKDIR)

    print(f"  {config.name}  ->  scenario_{name}.json")
    if dry_run:
        print(f"    [dry-run] {' '.join(cmd)}")
        return True

    scenarios_dir = instance_dir or location_dir / "scenarios"
    scenarios_dir.mkdir(parents=True, exist_ok=True)
    out_file = scenarios_dir / f"scenario_{name}.out"
    err_file = scenarios_dir / f"scenario_{name}.err"

    returncode, _ = run_container(cmd, cname, out_file, err_file, None, engine)
    ok = returncode == 0

    footer = f"--- exit: {returncode if returncode is not None else 'error'}"
    out_lines, err_lines = finish_capture(out_file, err_file, footer, ok)
    err_part = f"  stderr: {err_lines}L" if err_lines else ""
    print(f"    stdout: {out_lines}L{err_part}  (exit {returncode})")

    if not ok and returncode is not None:
        print(f"    FAILED (exit {returncode})", file=sys.stderr)
    return ok


def _generate_experiment(args, image: str) -> None:
    """--experiment: generate every instance of the file's "scenario_config" sweep."""
    try:
        spec = experiment_spec.load(args.experiment)
        configs = sweep_configs(scenario_params(spec), spec["location"])
    except (OSError, ValueError) as exc:
        sys.exit(f"ERROR: {exc}")
    loc = ROOT / spec["location"]
    if not loc.is_dir():
        sys.exit(f"No such location: {loc}")
    run_dir = args.run_dir or ROOT / "results" / spec["name"]

    total, errors = 0, 0
    with tempfile.TemporaryDirectory(prefix="scenario_configs_") as tmp:
        paths = []
        for instance, config in configs.items():
            path = Path(tmp) / f"{INSTANCE_PREFIX}{instance}.json"
            path.write_text(json.dumps(config, indent=4) + "\n")
            paths.append(path)
        selected = select(paths, args.instance, INSTANCE_PREFIX)
        if args.instance and not selected:
            fail_no_match(args.instance, list(configs))
        print(f"\n{loc.name} ({len(selected)} instance(s)) [from {args.experiment} -> {run_dir}]")
        for config in selected:
            total += 1
            if not _run_config(image, loc, config, args.dry_run, engine=args.engine,
                               cache_dir=args.sif_cache_dir,
                               instance_dir=run_dir / _instance_name(config)):
                errors += 1

    print(f"\nDone: {total - errors}/{total} succeeded.")
    if errors:
        sys.exit(1)


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
    parser.add_argument("--experiment", metavar="FILE", type=Path,
                        help="Generate the sweep an experiment JSON's \"scenario_config\" section "
                             "describes, writing each scenario to "
                             "<run-dir>/<instance>/scenario_<instance>.json. The location comes "
                             "from the file. No config files are kept: the section itself is the "
                             "config. This is the self-contained layout run_experiment.py uses.")
    parser.add_argument("--run-dir", metavar="DIR", type=Path,
                        help="With --experiment: where the instance directories go (default: "
                             "results/<name>/).")
    parser.add_argument("--no-pull", action="store_true",
                        help="Skip the up-front 'docker pull'. For a driver like "
                             "run_experiment.py that invokes this script once per attempt and "
                             "pulls each image once itself — without it, every invocation would "
                             "re-check the registry for an image that cannot change mid-run.")
    parser.add_argument("--version", choices=DOCKER_IMAGE_VERSIONS.keys(), default="stable",
                        help="Pick a docker image version ('local' is reserved for locally built "
                             "images).")
    add_engine_args(parser)
    args = parser.parse_args()

    if args.experiment and (args.location or args.config_dir):
        parser.error("--experiment takes its location from the file, and is its own config: "
                     "drop --location/--config-dir.")
    if args.run_dir and not args.experiment:
        parser.error("--run-dir requires --experiment.")
    if args.experiment and not args.experiment.is_file():
        parser.error(f"No such experiment file: {args.experiment}")
    if args.config_dir and not args.location:
        parser.error("--config-dir requires --location.")
    if args.config_dir and not args.config_dir.is_dir():
        parser.error(f"No such directory: {args.config_dir}")

    if not args.dry_run:
        ensure_runtime_ready(args.engine)
        # Apptainer images are staged once, up front, by
        # scripts/stage_apptainer_images.py -- there is nothing to pull here
        # (and compute nodes running under --engine apptainer have no
        # internet to pull with anyway).
        if args.engine == "docker" and not args.no_pull:
            ensure_pulled(DOCKER_IMAGE_VERSIONS[args.version])

    if args.experiment:
        _generate_experiment(args, DOCKER_IMAGE_VERSIONS[args.version])
        return

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
                               args.config_dir, args.engine, args.sif_cache_dir):
                errors += 1

    if args.instance and total == 0:
        fail_no_match(args.instance, available)

    print(f"\nDone: {total - errors}/{total} succeeded.")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
