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


# Docker Desktop on macOS can insist a bind source does not exist while it is
# plainly present on the host, failing the run with exit 125 in 0.0s.
#
# Measured on 2026-09-15: deleting a directory and recreating it poisons every
# path *beneath* it, not just the path itself. A brand-new child of a recreated
# ancestor fails, and keeps failing. So `rm -rf runs/` followed by a run into
# runs/<fresh timestamp>/... fails on every attempt — which looks exactly like
# the tool failing to produce a plan, and quietly fills an experiment with
# plan_produced=False instead of crashing.
#
# Of the remedies tried against a poisoned ancestor, only one works:
#
#   sleep 5s                 FAIL      writing a file into it   FAIL
#   stat()/listdir() on it   FAIL      bind-mounting it         ok
#
# Mounting the ancestor refreshes it, and its children then mount normally.
# Hence _warm_bind below, run only after a failure has already happened.
MOUNT_RACE_MESSAGE = "bind source path does not exist"
MOUNT_RACE_EXIT = 125


def _warm_bind(source: Path, image: str) -> None:
    """Bind-mount `source` and each ancestor under the working directory once.

    The exit codes are ignored on purpose: the container is expected to fail
    (it gets no sensible arguments), and it is the successful *mount* that
    refreshes Docker's view, not anything the container does. Bounded to the
    working directory so this never mounts / or a home directory, and given a
    short timeout in case an image waits for input when run bare.
    """
    root = Path.cwd().resolve()
    chain = [d for d in [*reversed(source.parents), source]
             if d == root or root in d.parents]
    for directory in chain:
        if not directory.is_dir():
            continue
        try:
            subprocess.run(
                ["docker", "run", "--rm", "--mount",
                 f"type=bind,source={directory},target=/warmup", image],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        except (subprocess.TimeoutExpired, OSError):
            pass


def _failed_bind_source(stderr: str) -> Path | None:
    """The bind source docker named in a 125, if that is what it complained about.

    Docker Desktop reports the path as the VM sees it, under /host_mnt, so that
    prefix has to come off before the result names anything on this filesystem.
    """
    for line in stderr.splitlines():
        if MOUNT_RACE_MESSAGE in line:
            path = line.split(MOUNT_RACE_MESSAGE, 1)[1].strip(": ")
            return Path(path.removeprefix("/host_mnt") or "/")
    return None


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

    A bind source docker cannot see (see MOUNT_RACE_MESSAGE) is warmed and
    retried once. Safe to retry because the container never started: nothing
    ran, nothing was written, and both output files are reopened truncated.
    """
    returncode, timed_out = _run_once(cmd, name, out_file, err_file, timeout)
    if returncode == MOUNT_RACE_EXIT and not timed_out:
        stderr = err_file.read_text(errors="replace") if err_file.exists() else ""
        source = _failed_bind_source(stderr)
        if source is not None:
            print(f"    docker cannot see {source}, which exists on disk — refreshing its "
                  f"parent directories and retrying", file=sys.stderr)
            _warm_bind(source, _image_of(cmd))
            returncode, timed_out = _run_once(cmd, name, out_file, err_file, timeout)
            if returncode == MOUNT_RACE_EXIT:
                print("    still unusable. A directory on that path was most likely deleted "
                      "and recreated; mount it once by hand to clear it, e.g.\n"
                      f"      docker run --rm --mount type=bind,source={source.parent},"
                      f"target=/x alpine true", file=sys.stderr)
    return returncode, timed_out


def _image_of(cmd: list[str]) -> str:
    """The image in a `docker run ... <image> [args]` command line.

    It is the first bare word after the flags: every option this module emits
    before it either starts with "--" or is that option's own value.
    """
    skip_next = False
    for token in cmd[2:]:
        if skip_next:
            skip_next = False
            continue
        if token.startswith("--"):
            skip_next = "=" not in token and token != "--rm"
            continue
        return token
    return "alpine"


def _run_once(cmd: list[str], name: str, out_file: Path, err_file: Path,
              timeout: int | None) -> tuple[int | None, bool]:
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
