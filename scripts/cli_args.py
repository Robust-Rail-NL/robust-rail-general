"""Argparse arguments shared by the run_*.py scripts.

run_generator/solver/planner/evaluator.py take the same --dry-run, --location,
--instance/--single, --no-pull and --version, with the same behaviour and
(near enough) the same help text. They are defined once here, so the wording
cannot drift between scripts. That includes --engine/--sif-cache-dir, which
run_experiment.py takes too.

Only what is truly shared belongs here. Options that differ per script
(--output-dir, --scenario, --timeout, ...) stay in the script that owns them.
"""

import argparse
from collections.abc import Iterable
from pathlib import Path

from scripts.docker_utils import DEFAULT_SIF_CACHE_DIR


def add_dry_run_arg(parser: argparse.ArgumentParser,
                    help: str = "Print docker commands without executing them.") -> None:
    parser.add_argument("--dry-run", action="store_true", help=help)


def add_location_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--location", metavar="NAME",
                        help="Restrict to a single Location_* directory.")


def add_instance_args(parser: argparse.ArgumentParser, what: str) -> None:
    """Add --instance and -s/--single; `what` names the file they select."""
    parser.add_argument("--instance", metavar="NAME",
                        help=f"Restrict to a single {what} (a pasted filename works too). "
                             f"Accepts shell-style wildcards; exits non-zero if it matches "
                             f"nothing.")
    parser.add_argument("-s", "--single", metavar="NAME",
                        help=f"Like --instance, but must select exactly one {what} across all "
                             f"locations (fails before running anything otherwise), and echoes "
                             f"the tool's stdout/stderr to the console as it runs, in addition "
                             f"to the .out/.err files. For watching one instance run.")


def apply_single(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Fold --single into --instance, and set args.tee for the container run.

    Everything --instance already does (the filter, the checks that other
    options need one, --output-dir's single-match rule) then applies unchanged.
    The exactly-one check across locations is separate: see
    instance_filter.ensure_single.
    """
    args.tee = args.single is not None
    if args.single is not None:
        if args.instance is not None:
            parser.error("--single and --instance are mutually exclusive.")
        args.instance = args.single


def add_no_pull_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--no-pull", action="store_true",
                        help="Skip the up-front 'docker pull'. For a driver like "
                             "run_experiment.py that invokes this script once per attempt and "
                             "pulls each image once itself — without it, every invocation would "
                             "re-check the registry for an image that cannot change mid-run.")


def add_version_arg(parser: argparse.ArgumentParser, versions: Iterable[str],
                    mentions_edge: bool = True) -> None:
    """Add --version over `versions` (the script's DOCKER_IMAGE_VERSIONS keys).

    mentions_edge: whether the help explains 'edge'. run_solver, run_planner and
    run_generator do; run_evaluator historically did not.
    """
    edge = ("; 'edge' tracks the newest not-yet-vetted push to the edge branch"
            if mentions_edge else "")
    parser.add_argument("--version", choices=list(versions), default="stable",
                        help=f"Pick a docker image version ('local' is reserved for locally "
                             f"built images{edge}).")


def add_engine_args(parser: argparse.ArgumentParser) -> None:
    """Add the --engine/--sif-cache-dir pair every run_*.py and
    run_experiment.py takes, so the choices, help text and default cache dir
    live in one place instead of five near-identical copies.
    """
    parser.add_argument("--engine", choices=["docker", "apptainer"], default="docker",
                        help="Container engine to run images under (default: docker). "
                             "'apptainer' is for a SLURM cluster with no docker daemon -- "
                             "scripts/stage_apptainer_images.py must be run first (on a host "
                             "with internet access) to populate --sif-cache-dir.")
    parser.add_argument("--sif-cache-dir", type=Path, default=DEFAULT_SIF_CACHE_DIR, metavar="DIR",
                        help=f"Where apptainer images are cached (default: {DEFAULT_SIF_CACHE_DIR}). "
                             "Ignored under --engine docker.")
