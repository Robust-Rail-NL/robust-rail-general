#!/usr/bin/env python3
"""Scan a run_experiment.py --output-dir results tree and compile two CSV reports.

Reads whatever result.json / eval_result.json / eval.out / eval.err files
run_experiment.py already wrote under <results-dir>/<instance>/{local_search,planning}/
-- this does not run anything itself.

local_search holds either one run directly (single --seed, or none) or one
subdirectory per seed (--num-seeds, seed1/, seed2/, ...) -- _tool_dirs below
detects which and yields one (label, dir) pair per actual run either way, so
everything downstream treats a 5-seed local_search the same as a solitary one.

  --runs-csv         One row per (instance, tool) attempt that was actually run
                      -- tool is "local_search_seed3" etc. when --num-seeds was
                      used, plain "local_search"/"planning" otherwise: the seed
                      actually used, plan_found (did the tool itself produce a
                      plan.json -- independent of what the evaluator later says
                      about it), timed_out, valid_plan (the evaluator's verdict
                      on that plan: yes/no, blank if no plan was ever produced
                      to evaluate, or "error" if the evaluator itself crashed
                      or produced no readable verdict -- kept apart from "no"
                      since that is not a determination the plan was invalid),
                      plan_length, move_actions and non_wait_actions
                      (counted from plan.json's own "actions" list -- total
                      actions, how many have taskType.predefined == "Move",
                      and how many do NOT have taskType.predefined == "Wait";
                      blank if no plan), and how many wall-clock seconds the
                      run took.
                      plan_found and valid_plan are deliberately separate
                      facts: a tool can find a plan the evaluator then rejects,
                      and collapsing that into one column read as "no" for
                      both looks identical to the tool failing outright.
  --feasibility-csv  One row per instance: feasible (some tool's plan was
                      confirmed valid) / infeasible (the evaluator flagged the
                      scenario itself, not just one plan) / unresolved
                      (neither), and whether an unresolved instance has been
                      "tested" -- re-attempted at or above --certify-threshold
                      seconds, the closest thing to a certification pass this
                      pipeline has.
  --solver-failures-csv / --planner-failures-csv
                      One row per (instance, tool) attempt that did NOT end
                      with an accepted plan -- instance, tool (carries the
                      seed suffix, e.g. "local_search_seed3"), seed, reason,
                      and seconds (the tool's own wall_seconds, i.e. how long
                      it ran before this outcome -- not the evaluator's,
                      which is typically much shorter and less telling).
                      reason is the evaluator's own "reason" (the same text
                      tally_failures.py classifies) when a plan was produced
                      and rejected, or one synthesized from result.json
                      (timed_out / exit_code) when no plan was ever produced
                      to evaluate. A tool split its own file rather than one
                      shared failures.csv, matching --runs-csv already
                      splitting by tool via its "tool" column.

eval_result.json's own "verdict" field does not currently distinguish a
scenario-level rejection from an ordinary plan rejection (both come out as
"rejected"), so the infeasible check here re-reads eval.out/eval.err directly
for "Issue detected with the Scenario" -- the same string sweep_seeds.py's own
classifier keys on.
"""

import argparse
import csv
import json
import sys
from pathlib import Path

# Matches run_experiment.py's FOLDER_NAMES: the folder name is the search
# approach, not the script/--tools name.
TOOL_FOLDERS = ("local_search", "planning")

DEFAULT_CERTIFY_THRESHOLD = 1800

# Shared with run_experiment.py, which appends rows in these same shapes while a
# sweep runs before this module recompiles all four files at the end.
RUN_FIELDNAMES = [
    "instance", "tool", "seed", "plan_found", "timed_out", "valid_plan",
    "plan_length", "move_actions", "non_wait_actions", "seconds",
    "trains_out", "pct_late", "avg_lateness", "pct_early", "avg_earliness",
]

REPO_ROOT = Path(__file__).resolve().parent.parent
FEASIBILITY_FIELDNAMES = ["instance", "classification", "tested"]
FAILURE_FIELDNAMES = ["instance", "tool", "seed", "reason", "seconds"]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def _tool_dirs(instance_dir: Path) -> list:
    """(label, dir) for every actual run under this instance: "local_search"/
    "planning" directly if that folder has a result.json of its own, or
    "local_search_seed<N>" per seed*/ subdirectory when --num-seeds was used
    (planning never has seeds -- run_planner.py has no seed concept).
    """
    pairs = []
    for folder in TOOL_FOLDERS:
        tool_dir = instance_dir / folder
        if (tool_dir / "result.json").exists():
            pairs.append((folder, tool_dir))
        elif tool_dir.is_dir():
            for seed_dir in sorted(tool_dir.glob("seed*")):
                if (seed_dir / "result.json").exists():
                    pairs.append((f"{folder}_{seed_dir.name}", seed_dir))
    return pairs


def _scenario_level_rejection(tool_dir: Path) -> bool:
    text = ""
    for name in ("eval.out", "eval.err"):
        f = tool_dir / name
        if f.exists():
            text += f.read_text(errors="replace")
    return "Issue detected with the Scenario" in text


def _plan_stats(tool_dir: Path) -> tuple:
    """(plan_length, move_actions, non_wait_actions) counted straight from
    plan.json's own "actions" list -- total actions, how many have
    taskType.predefined == "Move", and how many do NOT have
    taskType.predefined == "Wait". (None, None, None) if there's no plan to
    count.
    """
    plan = read_json(tool_dir / "plan.json")
    actions = plan.get("actions")
    if actions is None:
        return None, None, None
    moves = sum(1 for a in actions if (a.get("taskType") or {}).get("predefined") == "Move")
    non_waits = sum(1 for a in actions if (a.get("taskType") or {}).get("predefined") != "Wait")
    return len(actions), moves, non_waits


def _composition(units: list) -> tuple:
    """A train's make-up as an order-independent key: which types, how many."""
    return tuple(sorted((u.get("typePrefix"), u.get("carriages")) for u in units))


def departure_deltas(actions: list, scenario: dict) -> list:
    """Signed seconds each departing train left off its scheduled time.

    Positive is late, negative is early. One entry per Exit the plan makes that
    can be attributed to a departure request in the scenario's out[].

    An out[] request names the units it wants by type, not by id, so an Exit is
    matched to a request by composition -- the same basis TORS matches on. Where
    several requests want the same composition, the nearest departure time wins
    and each request is used once, so two interchangeable trains are not both
    charged against the earlier deadline. An Exit that matches nothing is left
    out rather than attributed to a guess, and a StandOut is skipped: a train
    staying in the yard has no departure time to be late for.
    """
    member_type = {}
    for group in ("in", "inStanding"):
        for train in scenario.get(group) or []:
            for member in train.get("members") or []:
                member_type[member["id"]] = (member.get("typePrefix"), member.get("carriages"))

    requests = []
    for request in scenario.get("out") or []:
        requests.append({
            "composition": _composition(request.get("trainUnits") or []),
            "departure": int(request.get("departure", 0)),
            "taken": False,
        })

    exits = sorted(
        (a for a in actions if (a.get("taskType") or {}).get("predefined") == "Exit"),
        key=lambda a: a["startTime"],
    )
    deltas = []
    for action in exits:
        members = (action.get("shuntingUnit") or {}).get("memberIDs") or []
        if not all(m in member_type for m in members):
            continue
        wanted = tuple(sorted(member_type[m] for m in members))
        candidates = [r for r in requests if not r["taken"] and r["composition"] == wanted]
        if not candidates:
            continue
        best = min(candidates, key=lambda r: abs(action["startTime"] - r["departure"]))
        best["taken"] = True
        deltas.append(int(action["startTime"]) - best["departure"])
    return deltas


def punctuality(deltas: list) -> dict:
    """Lateness and earliness of a plan's departures, as runs.csv reports them.

    The averages are over the trains actually late or actually early, not over
    every train, so "12% late, averaging 240s" reads as it sounds instead of
    being diluted towards zero by the punctual ones. Rounded to whole seconds.
    """
    if not deltas:
        return {"trains_out": 0, "pct_late": "", "avg_lateness": "",
                "pct_early": "", "avg_earliness": ""}
    late = [d for d in deltas if d > 0]
    early = [-d for d in deltas if d < 0]
    n = len(deltas)
    return {
        "trains_out": n,
        "pct_late": round(100 * len(late) / n, 1),
        "avg_lateness": round(sum(late) / len(late)) if late else 0,
        "pct_early": round(100 * len(early) / n, 1),
        "avg_earliness": round(sum(early) / len(early)) if early else 0,
    }


def _scenario_for(eval_result: dict, tool_dir: Path) -> dict:
    """The scenario an attempt ran against, found from what eval_result.json records.

    run_experiment.py keeps each scenario in its instance's own results
    directory, an ancestor of the attempt's tool_dir (<instance>/local_search[/seed<i>]);
    anything else ran against <location>/scenarios/.
    """
    location, scenario = eval_result.get("location"), eval_result.get("scenario")
    if not scenario:
        return {}
    for directory in list(tool_dir.parents)[:2]:
        if (directory / scenario).is_file():
            return read_json(directory / scenario)
    if not location:
        return {}
    return read_json(REPO_ROOT / location / "scenarios" / scenario)


def failure_reason(result: dict, eval_result: dict) -> str | None:
    """None if this attempt was not a failure (a plan was produced and the
    evaluator accepted it). Otherwise a short one-line reason: the evaluator's
    own "reason" (the same text tally_failures.py classifies) when a plan was
    produced and rejected, or one synthesized from the tool's own result.json
    (timed_out / exit_code) when no plan was ever produced to evaluate.
    """
    if not result.get("plan_produced"):
        if result.get("timed_out"):
            duration = result.get("max_duration")
            return f"timed out after {duration}s" if duration is not None else "timed out"
        exit_code = result.get("exit_code")
        return f"tool exited {exit_code}, no plan produced" if exit_code else "no plan produced"
    verdict = eval_result.get("verdict")
    if verdict == "accepted":
        return None
    return eval_result.get("reason") or (
        f"evaluator verdict: {verdict}" if verdict else "evaluator produced no verdict"
    )


def tool_rows(instance: str, tool: str, tool_dir: Path) -> tuple:
    """(run_row, failure_row) for one actual run, from a single read of
    result.json/eval_result.json. run_row is None if result.json doesn't
    exist yet (nothing has finished here). failure_row is None whenever
    run_row's own valid_plan is "yes" -- see failure_reason.
    """
    result = read_json(tool_dir / "result.json")
    if not result:
        return None, None

    eval_result = read_json(tool_dir / "eval_result.json")
    verdict = eval_result.get("verdict")
    plan_length, move_actions, non_wait_actions = _plan_stats(tool_dir)
    seed = result.get("seed", "")

    run_row = {
        "instance": instance,
        "tool": tool,
        "seed": seed,
        "plan_found": "yes" if result.get("plan_produced") else "no",
        "timed_out": "yes" if result.get("timed_out") else "no",
        "valid_plan": (
            "yes" if verdict == "accepted"
            else "error" if verdict == "error"
            else "no" if verdict
            else ""
        ),
        "plan_length": plan_length if plan_length is not None else "",
        "move_actions": move_actions if move_actions is not None else "",
        "non_wait_actions": non_wait_actions if non_wait_actions is not None else "",
        "seconds": result.get("wall_seconds", ""),
    }

    # How close the plan's departures came to the times asked for. Reported for
    # any plan that exists, accepted or not: a rejected plan's lateness is often
    # the reason it was rejected, and is worth seeing.
    plan = read_json(tool_dir / "plan.json")
    actions = plan.get("actions") or []
    scenario = _scenario_for(eval_result, tool_dir) if actions else {}
    run_row.update(punctuality(departure_deltas(actions, scenario) if scenario else []))

    reason = failure_reason(result, eval_result)
    failure_row = None if reason is None else {
        "instance": instance,
        "tool": tool,
        "seed": seed,
        "reason": reason,
        "seconds": result.get("wall_seconds", ""),
    }
    return run_row, failure_row


def instance_feasibility(instance: str, instance_dir: Path, certify_threshold: int) -> dict:
    any_solved = False
    any_infeasible = False
    any_certified = False
    for _, tool_dir in _tool_dirs(instance_dir):
        result = read_json(tool_dir / "result.json")
        eval_result = read_json(tool_dir / "eval_result.json")
        if eval_result.get("solved"):
            any_solved = True
        if _scenario_level_rejection(tool_dir):
            any_infeasible = True
        if (result.get("max_duration") or 0) >= certify_threshold:
            any_certified = True

    if any_solved:
        classification = "feasible"
    elif any_infeasible:
        classification = "infeasible"
    else:
        classification = "unresolved"

    return {
        "instance": instance,
        "classification": classification,
        "tested": "yes" if (classification == "unresolved" and any_certified) else "",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compile CSV reports from a run_experiment.py results directory.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("results_dir", type=Path,
                        help="The --output-dir a run_experiment.py run wrote to.")
    parser.add_argument("--runs-csv", type=Path, default=Path("runs.csv"),
                        help="Path to write the per-(instance, tool) run report (default: runs.csv).")
    parser.add_argument("--feasibility-csv", type=Path, default=Path("feasibility.csv"),
                        help="Path to write the per-instance feasibility report "
                             "(default: feasibility.csv).")
    parser.add_argument("--solver-failures-csv", type=Path, default=Path("solver_failures.csv"),
                        help="Path to write local_search (solver) failure reasons "
                             "(default: solver_failures.csv).")
    parser.add_argument("--planner-failures-csv", type=Path, default=Path("planner_failures.csv"),
                        help="Path to write planning (planner) failure reasons "
                             "(default: planner_failures.csv).")
    parser.add_argument("--certify-threshold", type=int, default=DEFAULT_CERTIFY_THRESHOLD,
                        metavar="SECONDS",
                        help="An unresolved instance is marked 'tested' if any of its recorded "
                             "runs used --max-duration at or above this (default: 1800).")
    args = parser.parse_args()

    if not args.results_dir.is_dir():
        sys.exit(f"No such directory: {args.results_dir}")

    instance_dirs = sorted(d for d in args.results_dir.iterdir() if d.is_dir())
    if not instance_dirs:
        sys.exit(f"No instance directories found under {args.results_dir}")

    run_rows = []
    solver_failure_rows = []
    planner_failure_rows = []
    feasibility_rows = []
    for instance_dir in instance_dirs:
        instance = instance_dir.name
        for tool_label, tool_dir in _tool_dirs(instance_dir):
            run_row, failure_row = tool_rows(instance, tool_label, tool_dir)
            if run_row:
                run_rows.append(run_row)
            if failure_row:
                # tool_label carries the seed suffix for solver (local_search,
                # local_search_seed3, ...) but is exactly "planning" for the
                # planner -- matches TOOL_FOLDERS/_tool_dirs above.
                failures = solver_failure_rows if tool_label.startswith("local_search") else planner_failure_rows
                failures.append(failure_row)
        feasibility_rows.append(
            instance_feasibility(instance, instance_dir, args.certify_threshold)
        )

    for path, fieldnames, rows in (
        (args.runs_csv, RUN_FIELDNAMES, run_rows),
        (args.feasibility_csv, FEASIBILITY_FIELDNAMES, feasibility_rows),
        (args.solver_failures_csv, FAILURE_FIELDNAMES, solver_failure_rows),
        (args.planner_failures_csv, FAILURE_FIELDNAMES, planner_failure_rows),
    ):
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    print(f"Wrote {len(run_rows)} run(s) to {args.runs_csv}")
    print(f"Wrote {len(feasibility_rows)} instance(s) to {args.feasibility_csv}")
    print(f"Wrote {len(solver_failure_rows)} solver failure(s) to {args.solver_failures_csv}")
    print(f"Wrote {len(planner_failure_rows)} planner failure(s) to {args.planner_failures_csv}")


if __name__ == "__main__":
    main()
