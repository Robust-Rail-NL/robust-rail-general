#!/usr/bin/env python3
"""Shared helpers for the run_generator/run_solver/run_evaluator/run_planner scripts.

Two container engines are supported: docker (the original, default) and
apptainer (for running the same pipeline on a SLURM cluster with no docker
daemon -- see scripts/stage_apptainer_images.py). Functions that differ by
engine take an explicit `engine` argument rather than reading a global, and
default to "docker" so every existing call site keeps working unchanged.
"""

import argparse
import importlib.util
import os
import shutil
import signal
import subprocess
import sys
import uuid
from pathlib import Path

# Shared by scripts/stage_apptainer_images.py (where it pulls to) and every
# run_*.py's --sif-cache-dir default (where it reads from) -- one literal
# instead of five copies that could drift apart.
DEFAULT_SIF_CACHE_DIR = Path.home() / "apptainer-images"


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


def sif_filename(image: str) -> str:
    """A deterministic, readable .sif filename for a docker image ref.

    "ghcr.io/robust-rail-nl/hip:latest" -> "ghcr.io_robust-rail-nl_hip_latest.sif".
    Both staging (apptainer_pull) and lookup (ensure_sif_present) derive the
    filename the same way from the image ref itself, not from whatever
    --version name resolved to it, so e.g. the generator's stable/
    stable-assert/edge -- three version names, one identical image -- share a
    single cached .sif instead of three copies of it.
    """
    return image.replace("/", "_").replace(":", "_") + ".sif"


def sif_path(image: str, cache_dir: Path) -> Path:
    return cache_dir / sif_filename(image)


def ensure_sif_present(image: str, cache_dir: Path, *, strict: bool = True) -> Path:
    """Resolve image -> its cached .sif, without ever trying to pull it.

    For the apptainer path on a SLURM compute node, which has no internet
    (see scripts/stage_apptainer_images.py) -- unlike ensure_pulled's docker
    path, there is no network fallback here. A missing .sif is a hard error
    pointing at the staging script, not something to silently fix mid-job.

    strict=False (for a --dry-run preview) skips that check and just returns
    the path a real run would resolve to, staged or not -- matching docker's
    own --dry-run, which never checks that an image has actually been pulled
    either. A real run always wants strict=True.
    """
    path = sif_path(image, cache_dir)
    if strict and not path.exists():
        sys.exit(f"ERROR: {path} not staged. Run scripts/stage_apptainer_images.py "
                 f"first (missing image: {image}).")
    return path


def apptainer_pull(image: str, cache_dir: Path, force: bool = False) -> Path | None:
    """Pull image into cache_dir as a .sif, skipping it if already cached.

    Used only by scripts/stage_apptainer_images.py (an interactive, once-off
    tool run by hand on a login node) -- unlike ensure_pulled, output is left
    to stream straight to the terminal rather than being captured, so a slow
    pull (the planner's Julia-heavy image especially) shows live progress.

    Pulled into a ".part" sibling first and only renamed into place once the
    pull succeeds, so a failed or interrupted pull never leaves a file at the
    real cache path for ensure_sif_present to mistake for a valid image.

    Skipped, like ensure_pulled, for bare local-build tags (no "/"): there is
    no registry to pull from, and this repo's apptainer path has no
    equivalent of docker's --version local (see docs/slurm-apptainer.md) --
    returns None rather than erroring, since a caller passing one through
    anyway (e.g. a stray --version local) should just see it skipped, not
    fail the whole staging run.
    """
    if "/" not in image:
        print(f"  Skipping {image} (bare local tag -- nothing to pull).")
        return None

    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = sif_path(image, cache_dir)
    if dest.exists() and not force:
        print(f"  Already staged: {dest.name}  ({image})")
        return dest

    tmp = dest.with_name(dest.name + ".part")
    tmp.unlink(missing_ok=True)
    print(f"  Pulling {image} -> {dest.name} ...")
    result = subprocess.run(["apptainer", "pull", str(tmp), f"docker://{image}"])
    if result.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        print(f"ERROR: 'apptainer pull' failed for {image} (exit {result.returncode}).",
              file=sys.stderr)
        sys.exit(1)
    tmp.replace(dest)
    return dest


def load_image_versions(script_path: Path) -> dict[str, str]:
    """Load a run_*.py's DOCKER_IMAGE_VERSIONS dict without running its CLI.

    Used by scripts/sweep_seeds.py (for the manifest), run_pipeline.py (to
    print/pass through what a --version resolves to) and run_experiment.py
    (to pull each image once up front) — three independent copies of this
    before being consolidated here. run_*.py are scripts meant to run as
    __main__, not package members, so this loads one in-process via importlib
    instead of a normal import.

    Each run_*.py does `from scripts.docker_utils import ...`, an absolute
    import that only resolves with the repo root on sys.path — true when it
    runs as __main__ via subprocess (cwd=ROOT puts it there), not true for
    this in-process load, so ensure it here too.
    """
    root = script_path.resolve().parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    spec = importlib.util.spec_from_file_location(script_path.stem, script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.DOCKER_IMAGE_VERSIONS


def container_name(prefix: str, instance: str) -> str:
    """A unique --name for one container, so a timeout can target that container.

    The uuid suffix (rather than just the instance name) avoids a "name already
    in use" conflict when a previous run's container of the same name is still
    being torn down.
    """
    return f"{prefix}-{instance}-{uuid.uuid4().hex[:8]}"


def build_run_cmd(engine: str, image: str, mounts: list[tuple[Path, str]], args: list[str], *,
                  name: str | None = None, cache_dir: Path | None = None,
                  strict: bool = True, workdir: str | None = None) -> list[str]:
    """Build one container invocation's argv, docker or apptainer, from engine-
    neutral pieces: mounts as (host source, in-container target) pairs, plus
    the image's own argv.

    Replaces each run_*.py's own inline `cmd = ["docker", "run", ...]`
    construction with one place that knows both engines' flag syntax -- see
    docs/slurm-apptainer.md for the full picture.

    docker: --rm, --name (only if given -- generator/evaluator never pass
    one, only solver/planner do, for run_container's kill-by-name timeout),
    --user uid:gid (skipped on Windows, where docker containers already run
    as an administrator-equivalent account), --mount type=bind per pair.

    apptainer: none of the above are meaningful -- there is no daemon to
    --rm from, no --name to kill by (run_container kills the process group
    instead), and it already runs as the invoking user. `apptainer run`, not
    `exec`: every image here (generator/solver/planner/evaluator) is built
    with a Docker ENTRYPOINT, and `args` are meant as arguments *to* it (the
    same contract `docker run <image> <args>` has) -- `apptainer run`
    invokes the .sif's converted-from-ENTRYPOINT runscript with `args`
    appended, where `apptainer exec` would instead try to execute `args[0]`
    itself as a command inside the container, which is never what an
    `--config`/`--mode`/etc. flag is. One --bind per mount pair and the
    resolved .sif (via ensure_sif_present, so a missing image fails here
    with a clear message rather than deeper inside a cryptic apptainer error
    -- unless strict=False, which a --dry-run preview wants: see
    ensure_sif_present).

    workdir sets --pwd, apptainer-only (docker already starts in the image's
    own WORKDIR on its own). Needed because apptainer, unlike docker, does
    NOT default to the image's configured WORKDIR -- it mirrors the *host's*
    current working directory inside the container instead, which breaks
    every one of these entrypoints, all of which use a path relative to a
    WORKDIR baked into their Dockerfile (e.g. generator's `python
    src/main.py`, expecting to run from /app): without --pwd, that resolves
    against wherever the container was invoked from on the host, not /app,
    and fails with a "no such file" naming a path that was never meant to
    exist. Caught 2026-09-24 running a bare `apptainer run <sif>` sanity
    check by hand -- see docs/slurm-apptainer.md.
    """
    if engine == "docker":
        cmd = ["docker", "run", "--rm"]
        if name is not None:
            cmd += ["--name", name]
        if sys.platform != "win32":
            cmd += ["--user", f"{os.getuid()}:{os.getgid()}"]
        for source, target in mounts:
            cmd += ["--mount", f"type=bind,source={source},target={target}"]
        cmd += [image, *args]
        return cmd
    if engine == "apptainer":
        if cache_dir is None:
            raise ValueError("build_run_cmd(engine='apptainer') requires cache_dir")
        sif = ensure_sif_present(image, cache_dir, strict=strict)
        cmd = ["apptainer", "run"]
        if workdir is not None:
            cmd += ["--pwd", workdir]
        for source, target in mounts:
            cmd += ["--bind", f"{source}:{target}"]
        cmd += [str(sif), *args]
        return cmd
    raise ValueError(f"unknown engine {engine!r}")


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
                  timeout: int | None, engine: str = "docker") -> tuple[int | None, bool]:
    """Run one container invocation, capturing stdout/stderr to files.

    Returns (returncode, timed_out); returncode is None if the run raised
    rather than exiting, in which case the exception is reported here.

    On timeout: for docker, the container is killed by name. subprocess's own
    timeout only kills the local `docker run` client, not the container it
    started, which keeps running under dockerd regardless — learned by hand
    on 2026-08-24, when killing run_planner.py left a container running for
    hours until it was separately `docker kill`ed. `--rm` still applies once
    the container stops, so a plain kill is enough and no separate `docker
    rm` is needed. For apptainer there is no daemon to leak into: the
    invoked process *is* the container, so killing its whole process group
    (see _run_once's start_new_session) is enough on its own.

    The Docker-Desktop bind-source race (see MOUNT_RACE_MESSAGE) is docker-
    specific and only checked for engine="docker": a bind source apptainer
    cannot see (see MOUNT_RACE_MESSAGE) is warmed and retried once. Safe to
    retry because the container never started: nothing ran, nothing was
    written, and both output files are reopened truncated.
    """
    returncode, timed_out = _run_once(cmd, name, out_file, err_file, timeout, engine)
    if engine == "docker" and returncode == MOUNT_RACE_EXIT and not timed_out:
        stderr = err_file.read_text(errors="replace") if err_file.exists() else ""
        source = _failed_bind_source(stderr)
        if source is not None:
            print(f"    docker cannot see {source}, which exists on disk — refreshing its "
                  f"parent directories and retrying", file=sys.stderr)
            _warm_bind(source, _image_of(cmd))
            returncode, timed_out = _run_once(cmd, name, out_file, err_file, timeout, engine)
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
              timeout: int | None, engine: str = "docker") -> tuple[int | None, bool]:
    returncode, timed_out = None, False
    try:
        with open(out_file, "w") as fout, open(err_file, "w") as ferr:
            # start_new_session so a timeout can kill this local client's
            # whole process group, not just the client itself -- unlike
            # subprocess.run's own timeout (which kills its direct child
            # automatically), a bare Popen.wait(timeout=...) leaves the
            # process running on TimeoutExpired, so that kill has to be done
            # by hand below for both engines, not just apptainer's.
            proc = subprocess.Popen(cmd, stdout=fout, stderr=ferr, start_new_session=True)
            try:
                returncode = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
                if engine == "docker":
                    # For apptainer the process group kill above already got
                    # everything -- there is no daemon for the container to
                    # keep running under once our own client is gone. Docker
                    # is different: the container lives under dockerd, a
                    # separate process tree the kill above never touches, so
                    # it has to be reached by name instead. See run_container.
                    subprocess.run(["docker", "kill", name],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                proc.wait()
    except Exception as exc:
        print(f"    ERROR: {exc}", file=sys.stderr)
    return returncode, timed_out


def ensure_runtime_ready(engine: str) -> None:
    """Exit with a clear message if the chosen engine isn't usable, before any
    container gets a chance to run under it.

    docker: delegates to ensure_docker_running (daemon reachability, not just
    the CLI being installed). apptainer: apptainer has no daemon, so the
    binary being on PATH is the whole check.
    """
    if engine == "docker":
        ensure_docker_running()
    elif engine == "apptainer":
        if shutil.which("apptainer") is None:
            print("ERROR: 'apptainer' command not found. Is it installed and on your PATH?",
                  file=sys.stderr)
            sys.exit(1)
    else:
        raise ValueError(f"unknown engine {engine!r}")


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
