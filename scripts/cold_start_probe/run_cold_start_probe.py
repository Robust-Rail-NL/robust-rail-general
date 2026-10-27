#!/usr/bin/env python3
"""Fully automated orchestrator for the cold-start probe -- replaces the
manual step-by-step in planner-cold-start-probe-steps.md with one process to
start once and leave running. Submits condition (a) as the first canary
(kept as condition (a)'s own result, not thrown away), then for each of
b/c/d: resubmits canaries until one comes back cold (total wall time at or
above --cold-threshold seconds), then submits that condition's 25-task
array and waits for it to finish, before moving on to the next condition.

Resumable: if run again against the same --out-base, already-completed
canaries and conditions are detected and reused/skipped rather than redone
-- important since getting a single cold canary can itself take hours of
real waiting, not something to casually throw away on a restart.

This process itself must keep running for however long the whole probe
takes (typically most of a day, dominated by waiting for genuinely cold
cache states, not compute) -- tmux/screen may not be available; use
`setsid nohup ... < /dev/null &` plus `disown` instead (see
planner-cold-start-probe-steps.md -- plain nohup+disown was found
insufficient against a stray Ctrl-C in the same terminal). Progress is
logged continuously to <out_base>/cold_start_probe.log, so it's checkable
at any time without interrupting the run:

    tail -n 50 <out_base>/cold_start_probe.log

Usage (from the repo root):
    python3 scripts/cold_start_probe/run_cold_start_probe.py <SCENARIO.json> <OUT_BASE>
        [--cold-threshold 45] [--poll-interval 60]
        [--canary-retry-interval 1800] [--canary-retry-backoff 1.5]
        [--canary-retry-max-interval 7200] [--max-wait-hours 48]
"""
import argparse
import getpass
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

_LOG_PATH: Path | None = None
ARRAY_TASKS = 25
# Must match the #SBATCH --job-name values in the two .sbatch scripts this
# orchestrator submits -- used to detect a stray job left over from a prior,
# now-dead orchestrator incarnation before submitting a new one. This only
# catches a stray *sub-job* (canary/array); it does nothing between
# sub-jobs, while the orchestrator itself is just sleeping -- see
# acquire_lock() below for the check that covers that gap.
OWN_JOB_NAMES = {"planner-timing-single", "planner-timing-array"}
LOCK_FILENAME = "orchestrator.lock"


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    if _LOG_PATH is not None:
        with open(_LOG_PATH, "a") as f:
            f.write(line + "\n")


def read_json_robust(path: Path) -> dict | None:
    """Parse path as JSON, tolerating (and logging) trailing extra data --
    e.g. from the two-concurrent-writers corruption a SLURM requeue could
    cause before run_planner_direct.py's metadata.json write became atomic
    (2026-10-17). Returns None if the file is missing or has no valid JSON
    at all at the start.
    """
    if not path.exists():
        return None
    text = path.read_text()
    try:
        obj, end = json.JSONDecoder().raw_decode(text)
    except json.JSONDecodeError:
        return None
    if text[end:].strip():
        log(f"WARNING: {path} has trailing data after its first JSON document "
            f"(likely leftover from a past concurrent-write corruption) -- using the first one.")
    return obj


def sbatch(args: list[str]) -> str:
    """Submit a job, return its (base) job ID."""
    result = subprocess.run(["sbatch", *args], capture_output=True, text=True)
    if result.returncode != 0:
        log(f"ERROR: sbatch {' '.join(args)} failed (exit {result.returncode}):")
        for line in result.stderr.splitlines() or ["(no stderr captured)"]:
            log(f"  {line}")
        result.check_returncode()
    match = re.search(r"Submitted batch job (\d+)", result.stdout)
    if not match:
        raise RuntimeError(f"Could not parse a job ID from sbatch's output: {result.stdout!r}")
    return match.group(1)


def job_finished(job_id: str) -> bool:
    """True once no task of job_id -- including any still-COMPLETING ones,
    and every task of an array -- shows up in squeue at all anymore. This
    only means the job left the queue, not that it succeeded -- a scancel'd
    job also leaves the queue. See job_states()."""
    result = subprocess.run(["squeue", "-j", job_id, "--noheader"],
                            capture_output=True, text=True)
    return result.stdout.strip() == ""


def job_states(job_id: str) -> list[str]:
    """Query sacct for job_id's terminal state(s): one per array task, or a
    single entry for a non-array job. Retries briefly since sacct can lag a
    few seconds behind squeue reporting the job gone. Returns [] if sacct
    never reports anything (treated as failure by the caller, not silently
    ignored)."""
    for _ in range(10):
        result = subprocess.run(["sacct", "-j", job_id, "-X", "--noheader", "--format=State"],
                                capture_output=True, text=True)
        states = [line.split()[0] for line in result.stdout.splitlines() if line.strip()]
        if states:
            return states
        time.sleep(2)
    return []


def _host_pid_alive(hostname: str, pid: int) -> bool | None:
    """True/False if liveness could be determined, None if it genuinely
    can't be (a different host, unreachable by ssh)."""
    if hostname == socket.gethostname():
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # exists, just owned by someone/something else
        else:
            return True
    try:
        result = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", hostname,
             "kill", "-0", str(pid)],
            capture_output=True, timeout=15)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return None


def acquire_lock(out_base: Path) -> Path:
    """Refuse to start if another orchestrator instance's lockfile points at
    a still-alive process -- this is the actual fix for the 2026-10-17/18
    corruption and the 2026-10-18 condition-c mix-up: both were two
    orchestrator instances racing against the same out_base, and
    refuse_if_stray_jobs_queued() only ever catches a stray *sub-job*, not a
    second orchestrator sitting in time.sleep() between canaries with no
    sub-job queued at all. Records (pid, hostname) so this also works when
    the orchestrator is a plain login-node nohup process rather than a
    SLURM job. A stale lockfile (dead pid) is taken over automatically; one
    that can't be verified (different, unreachable host) fails closed
    rather than risking a second writer. Known gap: a hard SIGKILL of the
    orchestrator leaves the lockfile behind, but since the recorded pid is
    then genuinely dead, the next start's liveness check reclaims it
    automatically -- no manual cleanup needed except in the unreachable-host
    case, or on PID reuse (rare, not specially guarded against here).
    """
    lock_path = out_base / LOCK_FILENAME
    if lock_path.exists():
        try:
            info = json.loads(lock_path.read_text())
            other_host, other_pid = info["hostname"], info["pid"]
        except (json.JSONDecodeError, KeyError, ValueError):
            log(f"WARNING: {lock_path} is unreadable -- treating as stale.")
        else:
            alive = _host_pid_alive(other_host, other_pid)
            if alive is True:
                log(f"ERROR: another orchestrator instance appears to still be running "
                    f"(pid {other_pid} on {other_host}, lockfile {lock_path}). Refusing to "
                    f"start -- two instances racing against the same out_base is exactly "
                    f"what caused the 2026-10-17/18 corruption. If that instance is genuinely "
                    f"dead (e.g. you already confirmed it's gone), remove the lockfile and retry.")
                sys.exit(1)
            if alive is None:
                log(f"ERROR: lockfile {lock_path} claims pid {other_pid} on {other_host}, a "
                    f"different host than this one ({socket.gethostname()}) -- could not verify "
                    f"by ssh whether it's still alive. Refusing to start to be safe. Check "
                    f"manually, then remove the lockfile if it's stale.")
                sys.exit(1)
            log(f"Lockfile {lock_path} refers to a dead process (pid {other_pid} on "
                f"{other_host}) -- treating as stale and taking over.")
    tmp_path = lock_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps({
        "pid": os.getpid(), "hostname": socket.gethostname(),
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
    }) + "\n")
    os.replace(tmp_path, lock_path)
    return lock_path


def release_lock(lock_path: Path) -> None:
    lock_path.unlink(missing_ok=True)


def refuse_if_stray_jobs_queued() -> None:
    """Exit loudly if a job from a prior, now-dead orchestrator incarnation
    is still queued/running -- killing this script (e.g. an accidental
    Ctrl-C) never cancels a SLURM job it already submitted, so restarting
    without checking first can leave two incarnations racing to write the
    same attempt-numbered directory. Found 2026-10-17: exactly this left two
    JSON documents concatenated in one metadata.json (and in the nohup.out
    log itself), silently corrupting results from more than just the one
    attempt that happened to crash loudly reading it back.
    """
    user = getpass.getuser()
    result = subprocess.run(["squeue", "-u", user, "-h", "-o", "%j %i"],
                            capture_output=True, text=True)
    stray = [line for line in result.stdout.splitlines()
            if line.split(" ", 1)[0] in OWN_JOB_NAMES]
    if stray:
        log("ERROR: found job(s) already in the queue from a previous orchestrator "
            "run -- refusing to start, to avoid two incarnations racing to write the "
            "same output directory:")
        for line in stray:
            log(f"  {line}")
        log("If these are genuinely stale (the orchestrator that submitted them is "
            "dead), cancel them first: scancel <jobid>. If another orchestrator "
            "instance is legitimately still running, don't start a second one.")
        sys.exit(1)


def wait_for_job(job_id: str, poll_interval: int, label: str) -> None:
    """Wait for job_id to leave the queue, then verify via sacct that it
    actually COMPLETED rather than being cancelled/failed/timed out --
    job_finished() alone can't tell the difference (a scancel'd job also
    just disappears from squeue). Found 2026-10-18: a manual `scancel` of
    everything mid-run would otherwise be silently read as success,
    producing an output directory that *looks* structurally complete
    (condition_complete() only checks metadata.json files exist) but was
    actually cut short."""
    log(f"waiting for {label} (job {job_id})...")
    while not job_finished(job_id):
        time.sleep(poll_interval)
    states = job_states(job_id)
    bad = [s for s in states if not s.startswith("COMPLETED")]
    if not states or bad:
        raise RuntimeError(
            f"{label} (job {job_id}) did not complete successfully "
            f"(sacct state(s): {states or ['none reported']}). If this was an intentional "
            f"scancel, the output directory for this step is incomplete -- don't resume "
            f"from it without removing it first.")
    log(f"{label} (job {job_id}) finished")


def _existing_canary_attempts(out_base: Path, label_prefix: str) -> list[tuple[int, Path]]:
    results = []
    for p in out_base.glob(f"{label_prefix}-canary-*"):
        try:
            n = int(p.name.rsplit("-", 1)[-1])
        except ValueError:
            continue
        results.append((n, p))
    return sorted(results)


def run_canary_until_cold(scenario: Path, out_base: Path, cold_threshold: float,
                          poll_interval: int, base_retry_interval: int, retry_backoff: float,
                          max_retry_interval: int, max_wait_hours: float,
                          label_prefix: str) -> Path:
    """Submit canaries (labelled so they're identifiable later) until one
    comes back cold; return that canary's own output directory. Resumes from
    whatever canary attempts already exist under out_base, reusing an
    already-cold one outright rather than resubmitting.

    The wait between warm attempts grows by retry_backoff each time (capped
    at max_retry_interval), rather than staying fixed at base_retry_interval
    -- added 2026-10-18 after watching condition (b) need 11 attempts at a
    flat 30-minute interval (5.5 hours) to see one cold result: if repeated
    canary touching itself keeps some shared cache state warm, a fixed short
    interval could in principle never let it cool, and even if it isn't
    that, escalating the gap is a more direct way to find out how long a
    gap is actually needed than repeating the same one and hoping variance
    helps. retry_backoff=1.0 keeps the old fixed-interval behavior exactly.
    On resume, the escalation picks up from however many consecutive warm
    attempts already exist, rather than resetting to the base interval.
    """
    existing = _existing_canary_attempts(out_base, label_prefix)
    for n, out_dir in existing:
        meta = read_json_robust(out_dir / "metadata.json")
        if meta and "start_time" in meta and "end_time" in meta:
            wall = meta["end_time"] - meta["start_time"]
            if wall >= cold_threshold:
                log(f"{label_prefix}: reusing existing cold canary attempt {n} "
                    f"({wall:.1f}s) from {out_dir}")
                return out_dir

    deadline = time.time() + max_wait_hours * 3600
    attempt = max((n for n, _ in existing), default=0)
    consecutive_warm = len(existing)  # all of `existing` are confirmed warm by this point
    while True:
        attempt += 1
        out_dir = out_base / f"{label_prefix}-canary-{attempt}"
        condition_label = f"canary-for-{label_prefix}-attempt-{attempt}"
        job_id = sbatch(["scripts/cold_start_probe/planner-timing-single.sbatch",
                        str(scenario), str(out_dir), condition_label])
        wait_for_job(job_id, poll_interval, f"{label_prefix} canary attempt {attempt}")
        meta = read_json_robust(out_dir / "metadata.json")
        if meta is None or "start_time" not in meta or "end_time" not in meta:
            raise RuntimeError(f"{label_prefix} canary attempt {attempt}: no usable "
                               f"metadata.json under {out_dir} after the job finished.")
        wall = meta["end_time"] - meta["start_time"]
        log(f"{label_prefix} canary attempt {attempt}: {wall:.1f}s total")
        if wall >= cold_threshold:
            log(f"{label_prefix}: cache is cold ({wall:.1f}s >= {cold_threshold}s), proceeding")
            return out_dir
        if time.time() > deadline:
            raise RuntimeError(f"{label_prefix}: cache never went cold within {max_wait_hours}h "
                               f"({attempt} attempt(s))")
        retry_interval = min(base_retry_interval * (retry_backoff ** consecutive_warm),
                             max_retry_interval)
        consecutive_warm += 1
        log(f"{label_prefix}: still warm ({wall:.1f}s < {cold_threshold}s), "
            f"retrying in {retry_interval:.0f}s (warm streak: {consecutive_warm})")
        time.sleep(retry_interval)


def condition_complete(out_dir: Path, expected_tasks: int = ARRAY_TASKS) -> bool:
    """True if out_dir already has every task's metadata.json, readable --
    i.e. this condition's array already ran to completion in a past run."""
    if not out_dir.is_dir():
        return False
    task_dirs = sorted(out_dir.glob("task_*"))
    if len(task_dirs) < expected_tasks:
        return False
    return all(read_json_robust(d / "metadata.json") is not None for d in task_dirs)


def main() -> None:
    global _LOG_PATH
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scenario", type=Path)
    parser.add_argument("out_base", type=Path)
    parser.add_argument("--cold-threshold", type=float, default=45.0,
                        help="Total wall seconds at/above which a canary counts as cold "
                             "(default: 45 -- matches the poster sweeps' own slow/fast split).")
    parser.add_argument("--poll-interval", type=int, default=60,
                        help="Seconds between squeue checks while a job is running (default: 60).")
    parser.add_argument("--canary-retry-interval", type=int, default=1800,
                        help="Base seconds to wait before re-trying a warm canary "
                             "(default: 1800 = 30min). Grows by --canary-retry-backoff each "
                             "consecutive warm attempt, capped at --canary-retry-max-interval.")
    parser.add_argument("--canary-retry-backoff", type=float, default=1.5,
                        help="Multiplier applied to the retry interval each consecutive warm "
                             "attempt (default: 1.5). With the default 1800s base: 1800, 2700, "
                             "4050, 6075s, ... capped at --canary-retry-max-interval. Pass 1.0 "
                             "for the old fixed-interval behavior.")
    parser.add_argument("--canary-retry-max-interval", type=int, default=7200,
                        help="Cap on the (possibly backed-off) retry interval, seconds "
                             "(default: 7200 = 2h). Irrelevant if --canary-retry-backoff is 1.0.")
    parser.add_argument("--max-wait-hours", type=float, default=48.0,
                        help="Give up waiting for a cold canary after this many hours, per "
                             "condition (default: 48).")
    args = parser.parse_args()

    args.out_base.mkdir(parents=True, exist_ok=True)
    _LOG_PATH = args.out_base / "cold_start_probe.log"
    refuse_if_stray_jobs_queued()
    lock_path = acquire_lock(args.out_base)
    try:
        log(f"Starting cold-start probe orchestrator. scenario={args.scenario} "
            f"out_base={args.out_base}")

        condition_dirs = {}

        # Condition (a) IS the first canary -- its own result is condition (a)'s
        # data, not thrown away.
        condition_dirs["condition-a"] = run_canary_until_cold(
            args.scenario, args.out_base, args.cold_threshold, args.poll_interval,
            args.canary_retry_interval, args.canary_retry_backoff, args.canary_retry_max_interval,
            args.max_wait_hours, "condition-a")
        log(f"Condition (a) complete: {condition_dirs['condition-a']}")

        for mode, label in [("shared", "condition-b"), ("local", "condition-c"),
                            ("warmup", "condition-d")]:
            out_dir = args.out_base / label
            if condition_complete(out_dir):
                log(f"{label}: already complete ({out_dir}), skipping")
            else:
                run_canary_until_cold(args.scenario, args.out_base, args.cold_threshold,
                                      args.poll_interval, args.canary_retry_interval,
                                      args.canary_retry_backoff, args.canary_retry_max_interval,
                                      args.max_wait_hours, label)
                job_id = sbatch(["--array=0-24", "scripts/cold_start_probe/planner-timing-array.sbatch",
                                mode, str(args.scenario), str(out_dir)])
                wait_for_job(job_id, args.poll_interval, label)
                log(f"{label} complete: {out_dir}")
            condition_dirs[label] = out_dir

        log("All conditions complete. Summarizing...")
        summary_path = args.out_base / "summary.csv"
        subprocess.run([sys.executable, "scripts/cold_start_probe/summarize_planner_timing.py",
                       *[str(d) for d in condition_dirs.values()], "--output", str(summary_path)],
                       check=True)
        log(f"Done. Summary: {summary_path}")
    finally:
        release_lock(lock_path)


if __name__ == "__main__":
    main()
