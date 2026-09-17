#!/usr/bin/env python3
"""Run solver and/or planner against one or all instances in a location and
record which were solved, for local solver-vs-planner comparison.

Drives run_generator.py / run_solver.py / run_planner.py / run_evaluator.py as
subprocesses via their --instance and --output-dir flags. Each (instance, tool)
attempt gets its own directory, named after the search approach rather than the
script that drives it:

  <output-dir>/<instance>/local_search/  plan.json, solver.out/.err, result.json,
                                         eval.out/.err/.txt, eval_result.json
  <output-dir>/<instance>/planning/      same layout

--num-seeds N runs the solver N times per instance instead of once, each seed
getting its own local_search/seed<i>/ subdirectory with that same layout
(planning is unaffected -- run_planner.py has no seed concept).
scripts/report_results.py and scripts/coverage_analysis.py detect and handle
both layouts.

result.json (written by run_solver.py/run_planner.py) records whether the tool
produced a plan; eval_result.json (written by run_evaluator.py, only when a
plan was produced) carries the "solved" verdict -- solved is decided by the
evaluator alone, never by the solver/planner's own exit code.

Runs run_generator.py first (cheap relative to solving/planning) so every
config has a matching scenario before instances are resolved. --config-dir
restricts both generation and the instances that follow it to one external
directory of configs, instead of the location's own configurations/ -- this is
how a custom instance set is run end to end.

Finishes by running scripts/report_results.py over --output-dir, writing
runs.csv and feasibility.csv there, then scripts/coverage_analysis.py, writing
coverage_analysis.txt (RQ1 coverage + Wilson intervals + exact McNemar test)
-- both skipped on --dry-run, since a dry run's results are never fresh.

progress.csv (instance, local_search, planning -- "done"/blank) is rewritten in
--output-dir after every (instance, tool) attempt finishes, whether that finish
came from a real evaluator call or from the tool failing/timing out before ever
reaching one -- a live view of how far a long run has gotten.
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
from scripts.docker_utils import ensure_docker_running, ensure_pulled, load_image_versions  # noqa: E402

# --tools/result.json still say "solver"/"planner" (they name the script, and
# the tool field run_solver.py and run_planner.py themselves write), but the
# per-instance output directory is named after the search approach instead.
FOLDER_NAMES = {"solver": "local_search", "planner": "planning"}

# Guards progress.csv: with --jobs > 1, several instances' worker threads call
# _write_progress concurrently, and each rewrites the whole file from scratch
# -- without this, two threads opening it "w" at the same time could interleave
# writes into a half-truncated file. all_results itself needs no such guard:
# each instance owns a disjoint sub-dict (all_results.setdefault(instance, {})),
# so concurrent reads/writes never touch the same key.
_progress_lock = threading.Lock()

# A certification pass is conventionally run at a multiple of the main budget,
# not the same T -- so the default threshold isn't just --max-duration itself.
CERTIFY_MULTIPLIER = 6


def _pull_once(steps: dict) -> None:
    """Pull each image this run needs, once, before any attempt starts.

    Every run_*.py pulls up front so a floating tag is never served stale, which
    is right when you invoke it yourself. But this driver invokes them once per
    (instance, tool, seed): a 180-instance sweep at 5 seeds is 900 invocations,
    so that same guarantee became 900 registry round-trips for images that
    cannot change mid-run — minutes of waiting, and 900 chances for a flaky
    registry to kill the sweep. Pulling here once and passing --no-pull down
    keeps the guarantee and drops the repetition.

    steps maps script name -> version key, e.g. {"run_solver.py": "stable"}.
    """
    seen = set()
    for script, version in steps.items():
        image = load_image_versions(ROOT / script)[version]
        if image not in seen:
            seen.add(image)
            ensure_pulled(image)


def _run_report(out_dir: Path, max_duration, certify_threshold) -> None:
    # --certify-threshold, if given directly, wins outright. Otherwise derive it
    # from --max-duration (this invocation's own budget input) rather than an
    # independently-guessed number; report_results.py's own default applies only
    # when neither --max-duration nor --certify-threshold was given.
    if certify_threshold is None and max_duration is not None:
        certify_threshold = CERTIFY_MULTIPLIER * max_duration
    subprocess.run([
        sys.executable, str(ROOT / "scripts" / "report_results.py"), str(out_dir),
        "--runs-csv", str(out_dir / "runs.csv"),
        "--feasibility-csv", str(out_dir / "feasibility.csv"),
        *(["--certify-threshold", str(certify_threshold)] if certify_threshold is not None else []),
    ], cwd=ROOT)


def _run_coverage_analysis(out_dir: Path) -> None:
    subprocess.run([
        sys.executable, str(ROOT / "scripts" / "coverage_analysis.py"), str(out_dir),
        "--output", str(out_dir / "coverage_analysis.txt"),
    ], cwd=ROOT)


def _run_generator(location: str, version: str, dry_run: bool, config_dir: Path = None,
                   instance: str = None) -> None:
    subprocess.run([
        sys.executable, str(ROOT / "run_generator.py"),
        "--location", location, "--version", version, "--no-pull",
        *(["--dry-run"] if dry_run else []),
        *(["--config-dir", str(config_dir)] if config_dir else []),
        *(["--instance", instance] if instance else []),
    ], cwd=ROOT)


def _instances_from_configs(config_dir: Path) -> list:
    """The instances a directory of configs will produce, straight from their names.

    run_generator.py passes --scenario-file explicitly, so a config named
    scenario_config_<X>.json always yields scenario_<X>.json. That is what
    makes this a filename computation rather than the mtime diff this used to
    need: the generator once derived scenario names from a config's *content*
    (location, train count, seed), so the only way to learn what a run had
    written was to compare scenarios/ before and after.
    """
    return [c.stem.removeprefix("scenario_config_")
            for c in sorted(config_dir.glob("scenario_config_*.json"))]


def _write_progress(out_dir: Path, instances: list, all_results: dict, num_seeds=None) -> None:
    """Rewrite progress.csv from the current in-memory results -- called after
    every (instance, tool[, seed]) attempt finishes, so it always reflects
    exactly how far the run has gotten, including instances not yet started
    (blank cells) and tools outside --tools for this run (also blank, since they
    were never in scope here, not because they're pending). With --num-seeds,
    local_search shows "k/N" until all N seeds for that instance are done, then
    "done" -- planning never has seeds, so it's unaffected.
    """
    with _progress_lock, open(out_dir / "progress.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["instance", "local_search", "planning"])
        writer.writeheader()
        for instance in instances:
            done = all_results.get(instance, {})
            if num_seeds:
                n_done = sum(1 for s in range(1, num_seeds + 1) if f"solver_seed{s}" in done)
                local_search = "done" if n_done == num_seeds else (f"{n_done}/{num_seeds}" if n_done else "")
            else:
                local_search = "done" if "solver" in done else ""
            writer.writerow({
                "instance": instance,
                "local_search": local_search,
                "planning": "done" if "planner" in done else "",
            })


def _version_for(tool: str, solver_version: str, planner_version: str) -> str:
    """The planner has its own independent version line (see run_planner.py's own
    DOCKER_IMAGE_VERSIONS comment) -- generator and solver share the 2.0.0-family
    version instead. Only for picking the solver-or-planner image itself: the
    evaluator always uses its own version regardless of which tool produced the
    plan (see the comment at its call site).
    """
    return planner_version if tool == "planner" else solver_version


def _run_tool(tool: str, location: str, instance: str, out_dir: Path, version: str,
              force: bool, dry_run: bool, max_duration, seed) -> dict:
    result_path = out_dir / "result.json"
    if result_path.exists() and not force:
        print(f"  SKIP {tool} (result.json exists): {out_dir}")
        return json.loads(result_path.read_text())

    script = "run_solver.py" if tool == "solver" else "run_planner.py"
    subprocess.run([
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
    ], cwd=ROOT)
    return json.loads(result_path.read_text()) if result_path.exists() else {
        "instance": instance, "tool": tool, "plan_produced": False,
    }


def _run_evaluator(location: str, instance: str, plan_path: Path, version: str,
                   force: bool, dry_run: bool) -> dict:
    eval_result_path = plan_path.parent / "eval_result.json"
    if eval_result_path.exists() and not force:
        print(f"  SKIP evaluator (eval_result.json exists): {plan_path.parent}")
        return json.loads(eval_result_path.read_text())

    subprocess.run([
        sys.executable, str(ROOT / "run_evaluator.py"),
        "--location", location, "--instance", instance, "--plan", str(plan_path),
        "--version", version, "--no-pull",
        *(["--dry-run"] if dry_run else []),
    ], cwd=ROOT)
    return json.loads(eval_result_path.read_text()) if eval_result_path.exists() else {
        "solved": False, "verdict": "error", "reason": "evaluator produced no eval_result.json",
    }


def _run_and_record(tool: str, location: str, instance: str, tool_dir: Path,
                    solver_version: str, planner_version: str, evaluator_version: str,
                    force: bool, dry_run: bool, max_duration, seed, results: dict,
                    key: str) -> None:
    version = _version_for(tool, solver_version, planner_version)
    run_result = _run_tool(tool, location, instance, tool_dir, version, force, dry_run,
                           max_duration, seed)
    eval_result = None
    # A dry run never produces a real plan.json, so there is nothing for the
    # evaluator to dry-run against either -- skip it rather than have it fail a
    # "no such plan file" check that would be misleading here. The evaluator has
    # its own independent version, never the plan's producer version: a planner
    # plan is still scored by the same evaluator build a solver plan would be,
    # otherwise "local" here would mean the planner's own dev image tag, which
    # the evaluator has no relation to. It also isn't tied to solver_version,
    # even though both default into the same family -- that "stable" alias is
    # deliberately float-forward and has bitten the solver once already (see
    # run_solver.py's own "stable" comment).
    if not dry_run and run_result.get("plan_produced"):
        eval_result = _run_evaluator(location, instance, tool_dir / "plan.json",
                                     evaluator_version, force, dry_run)
    results[key] = {"run": run_result, "eval": eval_result}
    solved = bool(eval_result and eval_result.get("solved"))
    print(f"  {instance} [{key}]  plan_produced={run_result.get('plan_produced')}  solved={solved}")


def _run_instance(location: str, instance: str, tools: list, out_dir: Path,
                  solver_version: str, planner_version: str, evaluator_version: str,
                  force: bool, dry_run: bool, max_duration, seed, num_seeds,
                  all_results: dict, all_instances: list) -> None:
    results = all_results.setdefault(instance, {})
    for tool in tools:
        if tool == "solver" and num_seeds:
            for s in range(1, num_seeds + 1):
                tool_dir = out_dir / instance / FOLDER_NAMES[tool] / f"seed{s}"
                _run_and_record(tool, location, instance, tool_dir,
                                solver_version, planner_version, evaluator_version,
                                force, dry_run, max_duration, s, results, f"solver_seed{s}")
                if not dry_run:
                    _write_progress(out_dir, all_instances, all_results, num_seeds)
        else:
            tool_dir = out_dir / instance / FOLDER_NAMES[tool]
            _run_and_record(tool, location, instance, tool_dir,
                            solver_version, planner_version, evaluator_version,
                            force, dry_run, max_duration, seed, results, tool)
            if not dry_run:
                _write_progress(out_dir, all_instances, all_results, num_seeds)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run solver and/or planner (each followed by the evaluator) against one or "
                    "every instance in a location, and record solved/not-solved.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--location", required=True, metavar="NAME")
    parser.add_argument("--instance", metavar="NAME",
                        help="Run a single instance instead of every scenario under the location. "
                             "Same name every step uses: scenario_<NAME>.json -> plan.json -> "
                             "eval_result.json. Mutually exclusive with --config-dir.")
    parser.add_argument("--tools", metavar="solver,planner", default="solver,planner",
                        help="Comma-separated subset of {solver,planner} to run (default: both).")
    parser.add_argument("--config-dir", metavar="DIR", type=Path,
                        help="Use scenario_config_*.json files from this directory instead of "
                             "<location>/configurations/. Restricts both generation and which "
                             "instances run afterward to this subset -- the way a custom instance "
                             "set is run. Mutually exclusive with --instance.")
    parser.add_argument("--output-dir", required=True, metavar="DIR")
    parser.add_argument("--generator-version", default="stable",
                        help="Docker image version for the generator -- kept separate from "
                             "--solver-version so scenario generation can be pinned or bumped "
                             "independently of the solve step. See run_generator.py --help.")
    parser.add_argument("--solver-version", default="stable",
                        help="Docker image version for the solver. See run_solver.py --help.")
    parser.add_argument("--planner-version", default="local",
                        help="Docker image version for the planner -- robust-rail-planner has its "
                             "own independent version line (default: local, i.e. whatever "
                             "'docker build -t planner:latest .' produced). See run_planner.py.")
    parser.add_argument("--evaluator-version", default="stable",
                        help="Docker image version for the evaluator -- kept separately settable "
                             "rather than inheriting the solver's. See run_evaluator.py --help.")
    parser.add_argument("--max-duration", type=int, metavar="SECONDS",
                        help="Wall-clock budget passed to each solver/planner run. Note it is not "
                             "enforced identically: the solver stops its own search there and "
                             "still writes its best plan, while the planner's container is killed "
                             "and writes nothing (ENHSP's own -timeout is dead code upstream). "
                             "Worth keeping in mind when reading a comparison.")
    parser.add_argument("--seed", type=int, metavar="N",
                        help="Passed through to run_solver.py's --seed (solver only). Without it "
                             "every run uses the same implicit seed, so this is for deliberately "
                             "varying it. Mutually exclusive with --num-seeds.")
    parser.add_argument("--num-seeds", type=int, metavar="N",
                        help="Run the solver N times per instance with seeds 1..N, each into its "
                             "own <instance>/local_search/seed<i>/. Solver only: --tools planner "
                             "still runs once. Mutually exclusive with --seed.")
    parser.add_argument("--certify-threshold", type=int, metavar="SECONDS",
                        help=f"Passed to report_results.py. Default: {CERTIFY_MULTIPLIER} x "
                             "--max-duration; report_results.py's own default applies if neither "
                             "this nor --max-duration is given.")
    parser.add_argument("--force", dest="force", action="store_true", default=True,
                        help="Re-run even if a result.json/eval_result.json exists (default: on).")
    parser.add_argument("--skip-existing", dest="force", action="store_false",
                        help="Skip (instance, tool) pairs that already have a result.json/"
                             "eval_result.json, instead of re-running them.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print docker commands without executing them (evaluator steps are "
                             "skipped, since a dry run never produces a plan to evaluate).")
    parser.add_argument("--jobs", type=int, default=1, metavar="N",
                        help="Run N instances concurrently (default: 1, sequential). Each "
                             "instance writes into its own <output-dir>/<instance>/ subtree and "
                             "gets its own uniquely-named containers (see "
                             "scripts/docker_utils.container_name), so instances never collide "
                             "with each other. Each attempt still blocks on its own docker "
                             "container, so this only helps when the host has spare CPU/IO to "
                             "run several at once. Ignored under --dry-run, which stays "
                             "sequential so its printed commands are easy to read in order.")
    args = parser.parse_args()
    if args.jobs < 1:
        sys.exit("--jobs must be at least 1.")

    loc = ROOT / args.location
    if not loc.is_dir():
        sys.exit(f"No such location: {loc}")
    if args.instance and args.config_dir:
        sys.exit("--instance and --config-dir are mutually exclusive.")
    if args.config_dir and not args.config_dir.is_dir():
        sys.exit(f"No such directory: {args.config_dir}")
    if args.seed is not None and args.num_seeds is not None:
        sys.exit("--seed and --num-seeds are mutually exclusive.")
    if args.num_seeds is not None and args.num_seeds < 1:
        sys.exit("--num-seeds must be at least 1.")

    tools = args.tools.split(",")
    for tool in tools:
        if tool not in ("solver", "planner"):
            sys.exit(f"Unknown tool {tool!r}; --tools takes a subset of solver,planner.")
    if args.num_seeds is not None and "solver" not in tools:
        sys.exit("--num-seeds only applies to the solver; include it in --tools.")

    if not args.dry_run:
        ensure_docker_running()
        steps = {"run_generator.py": args.generator_version,
                 "run_evaluator.py": args.evaluator_version}
        if "solver" in tools:
            steps["run_solver.py"] = args.solver_version
        if "planner" in tools:
            steps["run_planner.py"] = args.planner_version
        _pull_once(steps)

    source = f" from {args.config_dir}" if args.config_dir else ""
    print(f"Generating scenarios for {loc.name}{source}...", flush=True)
    _run_generator(args.location, args.generator_version, args.dry_run,
                   args.config_dir, args.instance)
    print()

    if args.config_dir:
        instances = _instances_from_configs(args.config_dir)
        if not instances:
            sys.exit(f"No scenario_config_*.json files under {args.config_dir}.")
    elif args.instance:
        instances = [args.instance]
    else:
        instances = [p.stem.removeprefix("scenario_")
                     for p in sorted(loc.glob("scenarios/scenario_*.json"))]
        if not instances and not args.dry_run:
            sys.exit(f"No scenario_*.json files under {loc}/scenarios/ "
                     f"(and none generated from configurations/ either).")

    if not args.dry_run:
        missing = [i for i in instances if not (loc / "scenarios" / f"scenario_{i}.json").exists()]
        if missing:
            sys.exit(f"Generator produced no scenario for: {', '.join(missing)}")

    out_dir = Path(args.output_dir)
    print(f"Running {len(instances)} instance(s) x {tools} against {loc.name}...\n", flush=True)

    all_results = {}
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        _write_progress(out_dir, instances, all_results, args.num_seeds)
    def run_one(instance: str) -> None:
        _run_instance(args.location, instance, tools, out_dir,
                      args.solver_version, args.planner_version, args.evaluator_version,
                      args.force, args.dry_run, args.max_duration, args.seed, args.num_seeds,
                      all_results, instances)

    if args.jobs > 1 and not args.dry_run:
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
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
        print(f"  {instance}: {line}", flush=True)

    if not args.dry_run:
        print(flush=True)
        _run_report(out_dir, args.max_duration, args.certify_threshold)
        print(flush=True)
        _run_coverage_analysis(out_dir)


if __name__ == "__main__":
    main()
