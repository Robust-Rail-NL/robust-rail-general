#!/usr/bin/env python3
"""Shared helpers for the run_generator/run_solver/run_evaluator/run_planner scripts."""

import importlib.util
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path


def ensure_pulled(image: str) -> None:
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


def load_image_versions(script_path: Path) -> dict[str, str]:
    root = script_path.resolve().parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    spec = importlib.util.spec_from_file_location(script_path.stem, script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.DOCKER_IMAGE_VERSIONS


def container_name(prefix: str, instance: str) -> str:
    return f"{prefix}-{instance}-{uuid.uuid4().hex[:8]}"

MOUNT_RACE_MESSAGE = "bind source path does not exist"
MOUNT_RACE_EXIT = 125


def _warm_bind(source: Path, image: str) -> None:
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
    for line in stderr.splitlines():
        if MOUNT_RACE_MESSAGE in line:
            path = line.split(MOUNT_RACE_MESSAGE, 1)[1].strip(": ")
            return Path(path.removeprefix("/host_mnt") or "/")
    return None


def run_container(cmd: list[str], name: str, out_file: Path, err_file: Path,
                  timeout: int | None) -> tuple[int | None, bool]:
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


def _count_lines(path: Path) -> int:
    try:
        with open(path, "rb") as f:
            count = sum(chunk.count(b"\n") for chunk in iter(lambda: f.read(1 << 20), b""))
    except OSError:
        return 0
    return count if _ends_with_newline(path) else count + 1


def _ends_with_newline(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            f.seek(-1, os.SEEK_END)
            return f.read(1) == b"\n"
    except OSError:
        return True


def finish_capture(out_file: Path, err_file: Path, footer: str, ok: bool) -> tuple[int, int]:
    had_stderr = err_file.exists() and err_file.stat().st_size > 0
    if ok and not had_stderr:
        err_file.unlink(missing_ok=True)
        return _count_lines(out_file), 0

    with open(err_file, "a") as f:
        if had_stderr and not _ends_with_newline(err_file):
            f.write("\n")
        f.write(footer if footer.endswith("\n") else footer + "\n")
    return _count_lines(out_file), _count_lines(err_file)


def ensure_docker_running() -> None:
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
