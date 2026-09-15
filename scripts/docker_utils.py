#!/usr/bin/env python3
"""Shared helpers for the run_generator/run_solver/run_evaluator/run_planner scripts."""

import shutil
import subprocess
import sys
import uuid
from pathlib import Path


def ensure_pulled(image: str) -> None:
    """Pull once, up front, so a floating tag (hip:latest, hip:edge, ...) is
    never silently served from a stale local cache — Docker's own default
    (`docker run` with no --pull) only pulls when the tag is absent locally,
    it does not special-case :latest or re-check a tag it already has.

    Called once per script invocation rather than passing `--pull always` to
    every `docker run` in the per-scenario/plan/config loop below: the image
    can't change mid-run, so re-checking the registry on every container start
    was one redundant round-trip per fixture for no benefit.

    Skipped for bare local-build tags (no "/", e.g. "hip:latest" built by
    docker-push.sh locally rather than pulled from ghcr.io): there is no
    registry to check, and `docker pull` would just fail trying to find one.
    """
    if "/" not in image:
        return

    print(f"Pulling {image} ...")
    result = subprocess.run(["docker", "pull", image], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if result.returncode != 0:
        print(f"ERROR: 'docker pull {image}' failed.", file=sys.stderr)
        stderr = result.stderr.decode(errors="replace").strip()
        if stderr:
            print(f"  docker said: {stderr.splitlines()[-1]}", file=sys.stderr)
        sys.exit(1)


def container_name(prefix: str, instance: str) -> str:
    """A unique --name for one container, so a timeout can target that container.

    The uuid suffix (rather than just the instance name) avoids a "name already
    in use" conflict when a previous run's container of the same name is still
    being torn down.
    """
    return f"{prefix}-{instance}-{uuid.uuid4().hex[:8]}"


def run_container(cmd: list[str], name: str, out_file: Path, err_file: Path,
                  timeout: int | None) -> tuple[int | None, bool]:
    """Run one `docker run --name <name> ...`, capturing stdout/stderr to files.

    Returns (returncode, timed_out); returncode is None if the run raised
    rather than exiting, in which case the exception is reported here.

    On timeout the container is killed by name. subprocess's own timeout only
    kills the local `docker run` client, not the container it started, which
    keeps running under dockerd regardless — learned by hand on 2026-08-24,
    when killing run_planner.py left a container running for hours until it was
    separately `docker kill`ed. `--rm` still applies once the container stops,
    so a plain kill is enough and no separate `docker rm` is needed.
    """
    returncode, timed_out = None, False
    try:
        with open(out_file, "w") as fout, open(err_file, "w") as ferr:
            result = subprocess.run(cmd, stdout=fout, stderr=ferr, timeout=timeout)
        returncode = result.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        subprocess.run(["docker", "kill", name],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as exc:
        print(f"    ERROR: {exc}", file=sys.stderr)
    return returncode, timed_out


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
