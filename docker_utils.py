#!/usr/bin/env python3
"""Shared helpers for the run_generator/run_solver/run_evaluator/run_planner scripts."""

import shutil
import subprocess
import sys


def pull_flag(image: str) -> list[str]:
    """--pull always for registry images, so a floating tag (hip:latest,
    hip:edge, ...) is never silently served from a stale local cache — Docker's
    own default (--pull missing) only pulls when the tag is absent locally, it
    does not special-case :latest or re-check a tag it already has.

    Omitted for bare local-build tags (no "/", e.g. "hip:latest" built by
    docker-push.sh locally rather than pulled from ghcr.io): there is no
    registry to check, and --pull always would just fail trying to find one.
    """
    return ["--pull", "always"] if "/" in image else []


def ensure_docker_running() -> None:
    """Exit with a clear message if docker isn't installed or the daemon isn't reachable.

    Without this, a dead daemon shows up as every single docker run failing with
    exit 125 and near-empty stderr, which looks identical to a scenario/config
    problem and sends people chasing the wrong thing.
    """
    if shutil.which("docker") is None:
        print("ERROR: 'docker' command not found. Is Docker installed and on your PATH?",
              file=sys.stderr)
        sys.exit(1)

    result = subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if result.returncode != 0:
        print("ERROR: Docker daemon is not running or not reachable "
              "(is Docker Desktop / the docker service started?).", file=sys.stderr)
        stderr = result.stderr.decode(errors="replace").strip()
        if stderr:
            print(f"  docker info said: {stderr.splitlines()[-1]}", file=sys.stderr)
        sys.exit(1)
