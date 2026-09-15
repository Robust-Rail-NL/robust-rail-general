#!/usr/bin/env python3
"""Run one scenario configuration over a range of seeds and classify each outcome.

A configuration plus a seed produces a scenario; feasibility is a property of
that scenario, not of the configuration. This sweeps the seed to measure how
often a configuration yields a feasible scenario, which is what makes a
"feasible only some of the time" fixture measurable.

Outcomes, most conclusive first:

  infeasible    The evaluator rejected the scenario before considering any
                plan (e.g. a train longer than the track it arrives on). This
                is plan-independent, so it is a proof rather than an opinion.
  feasible      The solver produced a plan with no constraint violations and
                the evaluator confirmed it valid.
  unknown       Anything else: the solver found only a violating plan, or the
                evaluator rejected the plan. A heuristic solver failing to
                find a plan is not evidence that none exists.
  generator     The generator itself failed, so there is no scenario to judge.

Example:
    ./sweep_seeds.py --location Location_KleineBinckhorst \\
                     --config feasible_small --seeds 1-30
"""

import argparse
import json
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
# Solver violation counters; a plan is unviolating only if all of them are zero.
# cr (crossings), sm (shunt moves) and rd (routing duration) are costs, not
# violations, so they are deliberately excluded.
VIOLATION_COUNTERS = ("dd", "da", "tlv", "cd", "um")


def _parse_seeds(spec: str) -> list[int]:
    seeds: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            seeds.extend(range(int(lo), int(hi) + 1))
        else:
            seeds.append(int(part))
    return seeds


def _run(cmd: list[str]) -> int:
    return subprocess.run(cmd, cwd=ROOT).returncode


def _solver_counters(plan_out: Path) -> dict[str, int] | None:
    """Pull the violation counters out of the solver's `Cost = ...` line."""
    if not plan_out.exists():
        return None
    for line in plan_out.read_text(errors="replace").splitlines():
        if "Cost = " not in line or "|" not in line:
            continue
        counters = {}
        for item in line.split("|", 1)[1].split(","):
            if "=" in item:
                key, _, value = item.partition("=")
                try:
                    counters[key.strip()] = int(float(value))
                except ValueError:
                    pass
        if counters:
            return counters
    return None


def _classify(loc: Path, base: str) -> tuple[str, str]:
    """Classify one seed's outcome as (bucket, reason)."""
    scenario = loc / "scenarios" / f"scenario_{base}.json"
    if not scenario.exists():
        return "generator", "no scenario file produced"

    def _read(suffix: str) -> str:
        path = loc / "evaluations" / f"eval_{base}.{suffix}"
        return path.read_text(errors="replace") if path.exists() else ""

    err, out = _read("err"), _read("out")
    # In EVAL_AND_STORE mode the rejection reason is written to the result file
    # rather than to stdout, so it has to be read back for a usable diagnosis.
    txt = _read("txt")

    # A scenario-level rejection is plan-independent, so it settles the question.
    for line in (err + out).splitlines():
        if "Issue detected with the Scenario" in line:
            return "infeasible", line.split("Scenario:", 1)[-1].strip()

    if "Assertion" in err and "failed" in err:
        assertion = next(
            (ln.strip() for ln in err.splitlines() if "Assertion" in ln), "assertion failed"
        )
        return "unknown", f"evaluator assertion: {assertion}"

    counters = _solver_counters(loc / "plans" / f"plan_{base}.out")
    if counters is None:
        return "unknown", "solver produced no cost line"

    violations = {k: v for k in VIOLATION_COUNTERS if (v := counters.get(k, 0))}

    if "The plan is valid" in out:
        if violations:
            # The evaluator accepted a plan the solver considers violating; worth
            # knowing about, so do not quietly call it feasible.
            return "unknown", f"evaluator valid but solver reports {violations}"
        return "feasible", "solver plan unviolating, evaluator confirms valid"

    reason = next(
        (
            ln.split("The action is invalid.", 1)[-1].strip().rstrip(".")
            for ln in (out + txt).splitlines()
            if "Scenario failed" in ln
        ),
        "plan rejected",
    )
    if violations:
        reason = f"{reason} (solver: {violations})"
    return "unknown", reason


# Directory a classified fixture is saved under. "unresolved" rather than
# "unknown" because the verdict is a statement about this pipeline at a moment in
# time, not about the scenario: fixing a solver bug can move a scenario out of it.
# The other two do not rot — an infeasible verdict is a proof, and a feasible one
# is witnessed by the plan saved beside it.
SAVE_DIRS = {"feasible": "feasible", "infeasible": "infeasible", "unknown": "unresolved"}


def _resolve_images(version: str) -> dict[str, str]:
    """The image each step would use, for the manifest."""
    import importlib.util

    images = {}
    for step in ("generator", "solver", "evaluator"):
        spec = importlib.util.spec_from_file_location(step, ROOT / f"run_{step}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        images[step] = module.DOCKER_IMAGE_VERSIONS.get(version, "?")
    return images


# Lines of the evaluation kept. The evaluator writes a full simulation trace,
# which runs to hundreds of kilobytes per run and dwarfs the scenario and plan it
# describes. It is also regenerable from those two. Only the tail carries the
# verdict and, for a rejected plan, the action it failed on.
EVAL_TAIL_LINES = 40


def _save_fixture(work: Path, base: str, dest: Path, name: str) -> dict[str, str]:
    """Copy one seed's scenario, plan and evaluation into dest. Returns what was saved.

    A scenario rejected before any plan has no plan or evaluation, so the set of
    files varies by outcome and the manifest records which are present.
    """
    dest.mkdir(parents=True, exist_ok=True)
    saved = {}
    for kind, source in (
        ("scenario", work / "scenarios" / f"scenario_{base}.json"),
        ("plan", work / "plans" / f"plan_{base}.json"),
    ):
        if source.exists() and source.stat().st_size > 0:
            target = dest / f"{kind}_{name}{source.suffix}"
            shutil.copy2(source, target)
            saved[kind] = target.name

    evaluation = work / "evaluations" / f"eval_{base}.txt"
    if evaluation.exists() and evaluation.stat().st_size > 0:
        lines = evaluation.read_text(errors="replace").splitlines()
        tail = lines[-EVAL_TAIL_LINES:]
        header = (
            f"[last {len(tail)} of {len(lines)} lines; "
            f"regenerate the full trace by evaluating the scenario and plan beside this file]\n"
            if len(lines) > len(tail)
            else ""
        )
        target = dest / f"eval_{name}.txt"
        target.write_text(header + "\n".join(tail) + "\n")
        saved["evaluation"] = target.name
    return saved


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sweep a scenario configuration over seeds and classify each outcome.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--location", required=True, help="Location_* directory name.")
    parser.add_argument("--config", required=True,
                        help="Configuration name without the scenario_config_ prefix or .json.")
    parser.add_argument("--seeds", default="1-20",
                        help="Seeds to sweep, e.g. '1-30' or '1,5,9-12' (default: 1-20).")
    parser.add_argument("--version", default="local",
                        help="Docker image version passed to each step (default: local).")
    parser.add_argument("--max-duration", type=int, default=20,
                        help="Solver MaxDuration in seconds per seed (default: 20). Rarely the "
                             "binding constraint: see --iterations.")
    parser.add_argument("--iterations", type=int, default=15000,
                        help="SimulatedAnnealing.IterationsUntilReset (default: 15000). Despite "
                             "the name, this is the search's hard iteration cap "
                             "(HIP's Program.cs passes it positionally as the 'iterations' "
                             "argument, not as a reset threshold), and it's usually what ends "
                             "the search long before --max-duration's wall-clock ceiling does. "
                             "HIP's own no-config default is 150000.")
    parser.add_argument("--json", metavar="FILE", help="Write the per-seed results as JSON.")
    parser.add_argument("--save", action="store_true",
                        help="Save each seed's scenario, plan and evaluation under "
                             "<location>/fixtures/<classification>/, and record them in "
                             "fixtures/manifest.json.")
    parser.add_argument("--keep", action="store_true",
                        help="Keep the scratch location directory for inspection.")
    args = parser.parse_args()

    source = ROOT / args.location
    config_path = source / "configurations" / f"scenario_config_{args.config}.json"
    if not config_path.exists():
        sys.exit(f"No such configuration: {config_path}")

    config = json.loads(config_path.read_text())
    if config.get("trains_given"):
        sys.exit(
            f"{config_path.name} has trains_given=true, so it does not vary with the seed."
        )

    seeds = _parse_seeds(args.seeds)
    # Scratch location, so a sweep never disturbs the checked-in scenarios/plans.
    work = ROOT / f"{args.location}__sweep"
    if work.exists():
        shutil.rmtree(work)
    try:
        for sub in ("configurations", "scenarios", "plans", "evaluations"):
            (work / sub).mkdir(parents=True)
        for name in ("location.json", "config.json"):
            if (source / name).exists():
                shutil.copy2(source / name, work / name)

        # run_solver.py reads its search parameters from here.
        (work / "config_solver.yaml").write_text(
            f"Mode: \"Standard\"\nDebugLevel: 0\n\n"
            f"TabuSearch:\n  Iterations: 40\n  IterationsUntilReset: 100\n"
            f"  TabuListLength: 16\n  Bias: 0.5\n\n"
            f"SimulatedAnnealing:\n  MaxDuration: {args.max_duration}\n"
            f"  StopWhenFeasible: true\n  IterationsUntilReset: {args.iterations}\n"
            f"  T: 15\n  A: 0.97\n  Q: 2000\n  Reset: 2000\n  Bias: 0.2\n"
            f"  IntensifyOnImprovement: false\n"
        )

        for seed in seeds:
            seeded = dict(config, seed=seed)
            # The generator derives the scenario name from everything after
            # "scenario_config_" in the config filename, so "_s<seed>" keeps
            # outputs distinct per seed.
            (work / "configurations" / f"scenario_config_{args.config}_s{seed}.json").write_text(
                json.dumps(seeded, indent=4)
            )

        location_arg = ["--location", work.name, "--version", args.version]
        print(f"Sweeping {len(seeds)} seeds of {args.config} in {args.location}\n")
        for step in ("run_generator.py", "run_solver.py", "run_evaluator.py"):
            print(f"--- {step}")
            # A non-zero exit is expected: individual seeds are allowed to fail.
            _run([sys.executable, str(ROOT / step), *location_arg])

        results = []
        for seed in seeds:
            # Mirrors main.py's default naming: everything after "scenario_config_"
            # in the per-seed config filename written above becomes the suffix.
            # Note run_generator.py's .out/.err use a different, config-based name.
            base = f"{config['location']}_{config['number_of_trains']}t_random_{seed}s_{args.config}_s{seed}"
            bucket, reason = _classify(work, base)
            results.append({"seed": seed, "outcome": bucket, "reason": reason, "base": base})

        counts = Counter(r["outcome"] for r in results)
        print(f"\n{'seed':>5}  {'outcome':<11} reason")
        for r in results:
            print(f"{r['seed']:>5}  {r['outcome']:<11} {r['reason'][:96]}")

        total = len(results)
        print(f"\n{'':>5}  {'-' * 60}")
        for bucket in ("feasible", "infeasible", "unknown", "generator"):
            if counts[bucket]:
                print(f"{counts[bucket]:>5}  {bucket:<11} {100 * counts[bucket] / total:.0f}%")
        print(f"{total:>5}  total")

        if args.save:
            fixtures = source / "fixtures"
            images = _resolve_images(args.version)
            measured = datetime.now().strftime("%Y-%m-%d")

            # Merge rather than replace: each sweep owns only its own config's
            # entries, so sweeping one config does not discard another's.
            manifest_path = fixtures / "manifest.json"
            manifest = (
                json.loads(manifest_path.read_text()) if manifest_path.exists() else {"fixtures": {}}
            )
            for key in [k for k, v in manifest["fixtures"].items() if v["config"] == args.config]:
                stale = fixtures / SAVE_DIRS.get(manifest["fixtures"][key]["outcome"], "unresolved")
                for filename in manifest["fixtures"][key].get("files", {}).values():
                    (stale / filename).unlink(missing_ok=True)
                del manifest["fixtures"][key]

            saved_count = 0
            for result in results:
                if result["outcome"] == "generator":
                    continue  # nothing was produced to save
                name = f"{args.config}_s{result['seed']:02d}"
                dest = fixtures / SAVE_DIRS[result["outcome"]]
                files = _save_fixture(work, result["base"], dest, name)
                if not files:
                    continue
                saved_count += 1
                manifest["fixtures"][name] = {
                    "config": args.config,
                    "seed": result["seed"],
                    "outcome": result["outcome"],
                    "reason": result["reason"],
                    "directory": SAVE_DIRS[result["outcome"]],
                    "files": files,
                    "measured": measured,
                    "images": images,
                    "solver_max_duration": args.max_duration,
                    "solver_iterations": args.iterations,
                }

            manifest["note"] = (
                "Classification is recorded per fixture, and the directory mirrors it. "
                "'feasible' and 'infeasible' do not rot: the first is witnessed by the "
                "plan saved beside it, the second is a scenario-level rejection and so a "
                "proof. 'unresolved' means this pipeline could not confirm a plan, which "
                "is a statement about the tools rather than the scenario — re-run the "
                "sweep after a solver or evaluator fix and some may move."
            )
            manifest["fixtures"] = dict(sorted(manifest["fixtures"].items()))
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
            print(f"\nSaved {saved_count} fixtures under {fixtures.relative_to(ROOT)}/")

        if args.json:
            Path(args.json).write_text(json.dumps(
                {
                    "location": args.location,
                    "config": args.config,
                    "version": args.version,
                    "max_duration": args.max_duration,
                    "iterations": args.iterations,
                    "counts": dict(counts),
                    "results": results,
                },
                indent=2,
            ) + "\n")
            print(f"\nWrote {args.json}")
    finally:
        if args.keep:
            print(f"\nScratch directory kept at {work}")
        elif work.exists():
            shutil.rmtree(work)


if __name__ == "__main__":
    main()
