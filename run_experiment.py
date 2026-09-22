#!/usr/bin/env python3
"""Run the experiment described by an experiment JSON, and record what solved.

    run_experiment.py scripts/example.json

The file is the whole interface (see scripts/experiment_spec.py): it names the
run, the location, the tools, the image versions, the budgets, and the scenario
sweep to generate. Nothing here overrides it, so the file stays an exact record
of what was run. "name" is the only name a run needs — configs land in
<location>/configurations/<name>/ and results in results/<name>/.

Drives run_generator.py / run_solver.py / run_planner.py / run_evaluator.py as
subprocesses. Generation goes first (cheap relative to solving/planning) so
every config has a matching scenario before instances are resolved, and the
generated directory then scopes the instance list for the rest of the run. Each
(instance, tool) attempt gets its own directory, named after the search approach
rather than the script that drives it:

  results/<name>/<instance>/local_search/  plan.json, solver.out/.err,
                                           result.json, eval.out/.err/.txt,
                                           eval_result.json
  results/<name>/<instance>/planning/      same layout

"num_seeds": N runs the solver up to N times per instance instead of once, each
seed getting its own local_search/seed<i>/ subdirectory with that same layout
(planning is unaffected — run_planner.py has no seed concept). It stops at the
first seed that solves: feasibility and coverage both ask only whether any seed
solved, so the rest would cost wall-clock without changing either answer. An
instance therefore has as many seed directories as it took, not always N.
scripts/report_results.py and scripts/coverage_analysis.py detect and handle
both layouts.

result.json (written by run_solver.py/run_planner.py) records whether the tool
produced a plan; eval_result.json (written by run_evaluator.py, only when a
plan was produced) carries the "solved" verdict — solved is decided by the
evaluator alone, never by the solver/planner's own exit code.

scripts/report_results.py's four reports — runs.csv, feasibility.csv,
solver_failures.csv and planner_failures.csv — fill in live under results/<name>/
over a long run. Each finished attempt appends its own row (one open, one
write), so the cost per attempt is constant no matter how far into a sweep it
lands. runs.csv and the two failures CSVs are already one row per
(instance, tool[, seed]), so an attempt's row depends on nothing but its own
directory; feasibility.csv is the one aggregate, and its row is appended once
an instance's every tool and seed has finished.

Those live rows are a progress view, not the record: re-running an attempt
appends a second row for it. Finishing the sweep runs report_results.py over
the whole tree once, overwriting all four files with a canonical full scan,
then scripts/coverage_analysis.py writes coverage_analysis.txt (RQ1 coverage +
Wilson intervals + exact McNemar test). Both are skipped on --dry-run, which
also appends nothing.
"""

import argparse
import csv
import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from scripts import experiment_spec  # noqa: E402
from scripts.docker_utils import ensure_docker_running, ensure_pulled, load_image_versions  # noqa: E402
from scripts.report_results import (  # noqa: E402
    DEFAULT_CERTIFY_THRESHOLD,
    FAILURE_FIELDNAMES,
    FEASIBILITY_FIELDNAMES,
    RUN_FIELDNAMES,
    failure_reason,
    instance_feasibility,
    tool_rows,
)

# --tools/result.json still say "solver"/"planner" (they name the script, and
# the tool field run_solver.py and run_planner.py themselves write), but the
# per-instance output directory is named after the search approach instead.
FOLDER_NAMES = {"solver": "local_search", "planner": "planning"}

# Guards the live CSV appends: with --jobs > 1, worker threads finish attempts
# around the same time and would otherwise interleave each other's rows.
# all_results needs no such guard — each instance owns a disjoint sub-dict, so
# concurrent writes never touch the same key.
_report_lock = threading.Lock()

# A certification pass is conventionally run at a multiple of the main budget,
# not the same T — so the default threshold isn't just --max-duration itself.
CERTIFY_MULTIPLIER = 6

# The four CSVs, appended a row at a time as the sweep runs and then recompiled
# in full by report_results.py at the end. The live rows are a progress view:
# a re-run appends a second row for the same attempt, and the final pass is
# what resolves that into one canonical set of files.
LIVE_CSVS = {
    "runs.csv": RUN_FIELDNAMES,
    "feasibility.csv": FEASIBILITY_FIELDNAMES,
    "solver_failures.csv": FAILURE_FIELDNAMES,
    "planner_failures.csv": FAILURE_FIELDNAMES,
}


def _certify_threshold(max_duration: int | None, certify_threshold: int | None) -> int:
    """--certify-threshold if given, else a multiple of --max-duration, else the
    same default report_results.py would have applied on its own.
    """
    if certify_threshold is not None:
        return certify_threshold
    if max_duration is not None:
        return CERTIFY_MULTIPLIER * max_duration
    return DEFAULT_CERTIFY_THRESHOLD


def _init_live_csvs(out_dir: Path) -> None:
    """Start each live CSV as a bare header, before any attempt runs."""
    for name, fieldnames in LIVE_CSVS.items():
        with open(out_dir / name, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=fieldnames).writeheader()


def _append_row(out_dir: Path, name: str, row: dict) -> None:
    """Append one row to a live CSV — one open, one write, no rescan."""
    with _report_lock:
        with open(out_dir / name, "a", newline="") as f:
            csv.DictWriter(f, fieldnames=LIVE_CSVS[name]).writerow(row)


def _append_attempt(out_dir: Path, instance: str, label: str, tool_dir: Path) -> None:
    """Append one finished attempt's runs.csv row, and its failure row if any.

    Reads only that attempt's own result.json/eval_result.json/plan.json, via
    the same tool_rows() report_results.py uses for its full scan, so the live
    rows and the final ones are built by one piece of code.
    """
    run_row, failure_row = tool_rows(instance, label, tool_dir)
    if run_row:
        _append_row(out_dir, "runs.csv", run_row)
    if failure_row:
        name = ("solver_failures.csv" if label.startswith(FOLDER_NAMES["solver"])
                else "planner_failures.csv")
        _append_row(out_dir, name, failure_row)


def _pull_once(steps: dict[str, str]) -> None:
    """Pull each image this run needs, once, before any attempt starts.

    Every run_*.py pulls up front so a floating tag is never served stale, but
    this driver invokes them once per (instance, tool, seed) — a 180-instance
    sweep at 5 seeds would be 900 registry round-trips for images that cannot
    change mid-run. Pulling here once and passing --no-pull down keeps the
    guarantee without the repetition.

    steps maps script name -> version key, e.g. {"run_solver.py": "stable"}.
    """
    seen = set()
    for script, version in steps.items():
        image = load_image_versions(ROOT / script)[version]
        if image not in seen:
            seen.add(image)
            ensure_pulled(image)


def _run_report(out_dir: Path, max_duration: int | None,
                certify_threshold: int | None) -> None:
    """Recompile all four CSVs from every result.json/eval_result.json on disk.

    Run once, at the end. It overwrites the rows appended live during the
    sweep, which is what resolves a re-run's duplicate rows into one canonical
    set of files.
    """
    subprocess.run([
        sys.executable, str(ROOT / "scripts" / "report_results.py"), str(out_dir),
        "--runs-csv", str(out_dir / "runs.csv"),
        "--feasibility-csv", str(out_dir / "feasibility.csv"),
        "--solver-failures-csv", str(out_dir / "solver_failures.csv"),
        "--planner-failures-csv", str(out_dir / "planner_failures.csv"),
        "--certify-threshold", str(_certify_threshold(max_duration, certify_threshold)),
    ], cwd=ROOT)


def _run_coverage_analysis(out_dir: Path) -> None:
    subprocess.run([
        sys.executable, str(ROOT / "scripts" / "coverage_analysis.py"), str(out_dir),
        "--output", str(out_dir / "coverage_analysis.txt"),
    ], cwd=ROOT)


def _run_generator(location: str, version: str, dry_run: bool, config_dir: Path,
                   total: int) -> None:
    """Run the generator over the sweep, reporting progress as one rewritten line.

    run_generator.py prints two lines per config, a few hundred for a sweep of
    any size, and only the count is interesting here. What it complains about
    is still shown, and the per-scenario detail stays in the .out/.err files it
    writes beside each scenario.
    """
    cmd = [
        sys.executable, str(ROOT / "run_generator.py"),
        "--location", location, "--version", version, "--no-pull",
        "--config-dir", str(config_dir),
        *(["--dry-run"] if dry_run else []),
    ]
    if dry_run:
        subprocess.run(cmd, cwd=ROOT)
        return

    # stderr is merged into stdout so this one loop drains both; left on its own
    # pipe, a long one could fill its buffer and wedge the sweep half way.
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    live = sys.stdout.isatty()
    done, problems = 0, []
    for line in proc.stdout:
        line = line.rstrip()
        # run_generator.py's per-config summary line: one per scenario finished.
        if line.startswith("    stdout:"):
            done += 1
            if live:
                print(f"\r  Generated {done}/{total}", end="", flush=True)
        elif line.startswith(("WARNING", "ERROR", "    FAILED")):
            problems.append(line.strip())
    proc.wait()

    print(f"\r  Generated {done}/{total}", flush=True)
    for problem in problems:
        print(f"    {problem}", file=sys.stderr, flush=True)


def _instances_from_configs(config_dir: Path) -> list[str]:
    """The instances a directory of configs will produce, straight from their names.

    run_generator.py passes --scenario-file explicitly, so a config named
    scenario_config_<X>.json always yields scenario_<X>.json — which is what
    makes this a filename computation rather than a scan of scenarios/.
    """
    return [c.stem.removeprefix("scenario_config_")
            for c in sorted(config_dir.glob("scenario_config_*.json"))]


def _generate_configs_from_json(loc: Path, experiment: Path, name: str) -> Path:
    """Expand the spec's "scenarios" block into <loc>/configurations/<name>/.

    Hands that directory back: it scopes both generation and the instance list
    for the rest of the run. The generator script reads the same experiment
    file, so the sweep parameters are never passed second-hand.
    """
    config_dir = loc / "configurations" / name
    print(f"Generating scenario configs for {loc.name} from {experiment} -> {config_dir}...",
          flush=True)
    result = subprocess.run([
        sys.executable, str(ROOT / "scripts" / "generate_experiment_configs.py"),
        "--from-json", str(experiment.resolve()),
    ], cwd=ROOT)
    if result.returncode != 0:
        # It has already said why, in the same terms this script would have —
        # both read the spec through experiment_spec. A traceback on top of
        # that message would only bury it.
        sys.exit(result.returncode)
    print()
    return config_dir


def _by_size(loc: Path, instances: list[str], config_dir: Path) -> list[str]:
    def trains(instance: str) -> float:
        configs = [config_dir / f"scenario_config_{instance}.json",
                   loc / "configurations" / f"scenario_config_{instance}.json"]
        for path in configs:
            try:
                return float(json.loads(path.read_text())["number_of_trains"])
            except (OSError, ValueError, KeyError, TypeError):
                pass
        try:
            scenario = json.loads((loc / "scenarios" / f"scenario_{instance}.json").read_text())
            return float(len(scenario.get("in") or []) + len(scenario.get("inStanding") or []))
        except (OSError, ValueError):
            return float("inf")

    return sorted(instances, key=trains)


def _version_for(tool: str, solver_version: str, planner_version: str) -> str:
    """The planner has its own independent version line (see run_planner.py's own
    DOCKER_IMAGE_VERSIONS comment) — generator and solver share the 2.0.0-family
    version instead. Only for picking the solver-or-planner image itself: the
    evaluator always uses its own version regardless of which tool produced the
    plan (see the comment at its call site).
    """
    return planner_version if tool == "planner" else solver_version


def _run_step(cmd: list[str], record_path: Path, what: str, dry_run: bool) -> None:
    """Run one attempt, swallowing its output unless it failed to leave a record.

    Everything a healthy attempt says is already on disk — solver.out/.err and
    result.json — so the child's own progress lines only repeat the summary
    line below, and under --jobs they interleave across threads. A missing
    record means it never got that far (docker down, a bad --instance, a
    crash), and then what it said is the only clue there is.

    A dry run is exempt: printing the docker commands is the whole point of it.
    """
    if dry_run:
        subprocess.run(cmd, cwd=ROOT)
        return

    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if record_path.exists():
        return
    # One string, one write: under --jobs two failures would otherwise interleave.
    said = "\n".join(f"    {line}" for line in (result.stdout + result.stderr).splitlines())
    print(f"  {what}: wrote no {record_path.name} (exit {result.returncode}) —\n{said}",
          file=sys.stderr, flush=True)


def _run_tool(tool: str, location: str, instance: str, out_dir: Path, version: str,
              dry_run: bool, max_duration: int | None, seed: int | None,
              planner_impl: str) -> dict:
    result_path = out_dir / "result.json"
    script = "run_solver.py" if tool == "solver" else "run_planner.py"
    _run_step([
        sys.executable, str(ROOT / script),
        "--location", location, "--instance", instance,
        "--output-dir", str(out_dir), "--version", version, "--no-pull",
        *(["--dry-run"] if dry_run else []),
        # Both tools take --max-duration, but it means different things: the
        # solver's own annealing budget (clean stop, best plan still written)
        # versus an external kill for the planner, which has no working internal
        # bound. See run_planner.py's --max-duration help.
        *(["--max-duration", str(max_duration)] if max_duration is not None else []),
        # --seed is solver-only; run_planner.py has no seed concept at all.
        *(["--seed", str(seed)] if seed is not None and tool == "solver" else []),
        # --planner is planner-only; run_solver.py has no such flag at all.
        *(["--planner", planner_impl] if tool == "planner" else []),
    ], result_path, f"{instance} [{tool}]", dry_run)
    return json.loads(result_path.read_text()) if result_path.exists() else {
        "instance": instance, "tool": tool, "plan_produced": False,
    }


def _run_evaluator(location: str, instance: str, plan_path: Path, version: str,
                   dry_run: bool) -> dict:
    eval_result_path = plan_path.parent / "eval_result.json"
    _run_step([
        sys.executable, str(ROOT / "run_evaluator.py"),
        "--location", location, "--instance", instance, "--plan", str(plan_path),
        "--version", version, "--no-pull",
        *(["--dry-run"] if dry_run else []),
    ], eval_result_path, f"{instance} [evaluator]", dry_run)
    return json.loads(eval_result_path.read_text()) if eval_result_path.exists() else {
        "solved": False, "verdict": "error", "reason": "evaluator produced no eval_result.json",
    }


# The instance column, wide enough for the sweep's own names; a longer one from
# somewhere else just pushes the rest of the row right.
INSTANCE_WIDTH = 24
REASON_WIDTH = 46


def _describe(instance: str) -> str:
    """A sweep instance name as readable columns: " 10 trains  FIFO    #3".

    generate_experiment_configs.py names them custom_<trains>_<matching>_<n>.
    Anything else — a hand-written fixture — is shown as it is.
    """
    parts = instance.split("_")
    if len(parts) == 4 and parts[0] == "custom" and parts[1].isdigit() and parts[3].isdigit():
        _, trains, matching, number = parts
        return f"{trains:>3} trains  {matching:<6}  #{number:<3}"
    return f"{instance:<{INSTANCE_WIDTH}}"


def _status(run_result: dict, eval_result: dict | None, dry_run: bool) -> str:
    """How one attempt ended, in the same words the failures CSV will use.

    "solved" means a plan was produced and the evaluator accepted it — the only
    outcome that counts. Everything else is why not: a timeout, a tool that
    exited without a plan, or the evaluator's own reason for rejecting one.
    """
    if dry_run:
        return "dry run"
    reason = failure_reason(run_result, eval_result or {})
    if reason is None:
        return "solved"
    return reason if len(reason) <= REASON_WIDTH else reason[:REASON_WIDTH - 1] + "…"


def _run_and_record(tool: str, location: str, instance: str, tool_dir: Path,
                    solver_version: str, planner_version: str, evaluator_version: str,
                    dry_run: bool, max_duration: int | None, seed: int | None,
                    planner_impl: str, results: dict, key: str) -> bool:
    """Run one attempt and record it. Returns whether the evaluator accepted its plan."""
    version = _version_for(tool, solver_version, planner_version)
    run_result = _run_tool(tool, location, instance, tool_dir, version, dry_run,
                           max_duration, seed, planner_impl)
    eval_result = None
    # A dry run never produces a real plan.json, so there is nothing for the
    # evaluator to dry-run against — skip it rather than have it fail a
    # misleading "no such plan file" check. The evaluator always uses its own
    # independent version, never the plan producer's: a planner plan must be
    # scored by the same evaluator build a solver plan would be.
    if not dry_run and run_result.get("plan_produced"):
        eval_result = _run_evaluator(location, instance, tool_dir / "plan.json",
                                     evaluator_version, dry_run)
    results[key] = {"run": run_result, "eval": eval_result}
    wall = run_result.get("wall_seconds")
    print(f"  {_describe(instance)}  {key:<16}  "
          f"{f'{wall:.1f}s' if isinstance(wall, (int, float)) else '':>7}  "
          f"{_status(run_result, eval_result, dry_run)}", flush=True)
    return bool(eval_result and eval_result.get("solved"))


def _run_instance(location: str, instance: str, tools: list[str], out_dir: Path,
                  solver_version: str, planner_version: str, evaluator_version: str,
                  dry_run: bool, max_duration: int | None,
                  certify_threshold: int | None, seed: int | None, num_seeds: int | None,
                  planner_impl: str, all_results: dict) -> None:
    results = all_results.setdefault(instance, {})
    for tool in tools:
        if tool == "solver" and num_seeds:
            for s in range(1, num_seeds + 1):
                label = f"{FOLDER_NAMES[tool]}_seed{s}"
                tool_dir = out_dir / instance / FOLDER_NAMES[tool] / f"seed{s}"
                solved = _run_and_record(tool, location, instance, tool_dir,
                                         solver_version, planner_version, evaluator_version,
                                         dry_run, max_duration, s, planner_impl, results,
                                         f"solver_seed{s}")
                if not dry_run:
                    _append_attempt(out_dir, instance, label, tool_dir)
                # Both things the seeds feed — feasibility.csv and the RQ1
                # coverage count — ask only whether ANY seed solved, so the
                # remaining seeds cannot change either answer. Retrying is only
                # worth the wall-clock while the instance is still unsolved.
                if solved:
                    break
        else:
            label = FOLDER_NAMES[tool]
            tool_dir = out_dir / instance / label
            _run_and_record(tool, location, instance, tool_dir,
                            solver_version, planner_version, evaluator_version,
                            dry_run, max_duration, seed, planner_impl, results, tool)
            if not dry_run:
                _append_attempt(out_dir, instance, label, tool_dir)

    # Every tool and seed for this instance has finished, so its feasibility
    # row — the one aggregate of the four, over this instance's attempts only —
    # can be settled now rather than recomputed after each attempt.
    if not dry_run:
        _append_row(out_dir, "feasibility.csv",
                    instance_feasibility(instance, out_dir / instance,
                                         _certify_threshold(max_duration, certify_threshold)))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the experiment described by an experiment JSON: generate its "
                    "scenarios, run each tool against them, evaluate every plan, and report.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("experiment", metavar="FILE", type=Path,
                        help="The experiment JSON (see scripts/example.json). It supplies the "
                             "name, location, tools, versions, budgets and scenario sweep for "
                             "the whole run — there is nothing to override here, so the file is "
                             "an exact record of what was run.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print docker commands without executing them (evaluator steps are "
                             "skipped, since a dry run never produces a plan to evaluate).")
    args = parser.parse_args()

    if not args.experiment.is_file():
        sys.exit(f"No such experiment file: {args.experiment}")
    try:
        spec = experiment_spec.load(args.experiment)
    except (OSError, ValueError) as exc:
        sys.exit(f"ERROR: {exc}")

    name, location = spec["name"], spec["location"]
    loc = ROOT / location
    if not loc.is_dir():
        sys.exit(f"No such location: {loc}")
    tools = spec["tools"]
    versions = spec[experiment_spec.VERSIONS_KEY]
    max_duration, certify_threshold = spec["max_duration"], spec["certify_threshold"]

    # One name for the whole run: its configs, and its results.
    out_dir = ROOT / "results" / name
    config_dir = _generate_configs_from_json(loc, args.experiment, name)

    if not args.dry_run:
        ensure_docker_running()
        steps = {"run_generator.py": versions["generator"],
                 "run_evaluator.py": versions["evaluator"]}
        for tool in tools:
            steps[f"run_{tool}.py"] = versions[tool]
        _pull_once(steps)

    # Resolved before generating, not after: it is the denominator of the
    # progress count, and an empty sweep is worth catching before the run.
    instances = _instances_from_configs(config_dir)
    if not instances:
        sys.exit(f"No scenario_config_*.json files under {config_dir}.")

    print(f"Generating scenarios for {loc.name} from {config_dir}...", flush=True)
    _run_generator(location, versions["generator"], args.dry_run, config_dir, len(instances))
    print()

    if not args.dry_run:
        missing = [i for i in instances if not (loc / "scenarios" / f"scenario_{i}.json").exists()]
        if missing:
            sys.exit(f"Generator produced no scenario for: {', '.join(missing)}")
    instances = _by_size(loc, instances, config_dir)

    print(f"Running {name}: {len(instances)} instance(s) x {tools} against {loc.name}, "
          f"smallest first -> {out_dir}\n", flush=True)
    print(f"  {'instance':<{INSTANCE_WIDTH}}  {'tool':<16}  {'time':>7}  status", flush=True)

    all_results = {}
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        _init_live_csvs(out_dir)

    def run_one(instance: str) -> None:
        _run_instance(location, instance, tools, out_dir,
                      versions["solver"], versions["planner"], versions["evaluator"],
                      args.dry_run, max_duration, certify_threshold,
                      spec["seed"], spec["num_seeds"], spec["planner"], all_results)

    if spec["jobs"] > 1 and not args.dry_run:
        with ThreadPoolExecutor(max_workers=spec["jobs"]) as pool:
            # list(), not just submit(): forces every future's result (or
            # exception) before moving on to the summary below, the same as the
            # sequential loop would.
            list(pool.map(run_one, instances))
    else:
        for instance in instances:
            run_one(instance)

    print("\n--- Summary ---", flush=True)
    for instance, per_tool in all_results.items():
        line = "  ".join(
            f"{tool}={'solved' if (r['eval'] and r['eval'].get('solved')) else 'unsolved'}"
            for tool, r in per_tool.items()
        )
        print(f"  {_describe(instance)}  {line}", flush=True)

    if not args.dry_run:
        print(flush=True)
        _run_report(out_dir, max_duration, certify_threshold)
        print(flush=True)
        _run_coverage_analysis(out_dir)



if __name__ == "__main__":
    main()
