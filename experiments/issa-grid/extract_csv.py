#!/usr/bin/env python3
"""Turn sweep output directories into Issa's CSV, one row per run.

usage: extract_csv.py --run off=DIR[:ARRAYID,...] --run on=DIR[:ARRAYID,...] [--sacct sacct.txt] -o issa_grid.csv

DIR is a run_experiment.py / slurm output directory: <DIR>/<instance>/{local_search[/seedN],planning[-IMPL]}/.
The servicing flag is not in the instance name, so each servicing variant is its own DIR.

Every task of the sweep gets a row, including a task that never wrote result.json (for example one killed by
the out-of-memory killer). The task list comes from DIR/tasks.tsv (the SLURM manifest); a DIR without one (a
local run_experiment.py run) is scanned for the tool folders that exist instead.

--sacct FILE joins SLURM's own accounting onto the rows. Produce it on the cluster with
    sacct -j ID1,ID2,... -P -n -o JobID,Partition,NodeList,Elapsed,MaxRSS,State > sacct.txt
and list the array job ids of each DIR after a colon (--run on=DIR:110372). A task's row is matched on
<array id>_<tasks.tsv index>. It adds slurm_state, partition, node and maxrss_mb, and it is the only source of
"oom" for a task that left no result.json.

Columns: Issa's eight (type-solver, num_trains, servicing, matching-order, instance-num, runtime,
expanded-states, solution-length), then valid, outcome (valid | invalid | unevaluated | timeout | oom | crash |
no_plan | no_scenario | no_result | slurm_<state>); no_scenario means the generator refused to
make the scenario (for example 1 train with servicing in a 1440 window), so the cell cannot exist, reason (the evaluator's reason for an invalid plan), and the details.

Planner stage lines in planner.out (planner images from 2026-11-06 on):
    TIMING stage=<pddl_conversion|search|planner_process|enhsp_process|validation|json_conversion|total> seconds=<float>
    STATS expanded=<int> plan_length=<int>
Solver images from the same date end solver.out with
    STATS search_seconds=.. neighbors=.. iterations=.. feasible=true|false time_to_best_seconds=..
Without them those columns stay empty; the PDDL plan length falls back to the older "plan length N"
(symbolic-rail) / "Plan length: N steps" (enhsp) lines.

search_s is each planner's own search time and is NOT comparable across planners (ENHSP's "Planning Time"
excludes JVM start-up, parsing and grounding; symbolic-rail's includes only the planner call, not Julia
start-up). planner_process_s covers the whole planner subprocess for both and is the comparable one.
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

COLUMNS = ["type-solver", "num_trains", "servicing", "matching-order", "instance-num", "runtime",
           "expanded-states", "solution-length", "valid", "outcome", "reason", "timed_out", "exit_code",
           "plan_produced", "slurm_state", "partition", "node", "maxrss_mb",
           "pddl_conversion_s", "search_s", "json_conversion_s", "pddl_plan_length", "json_actions",
           "solver_neighbors", "time_to_best_s", "solver_feasible", "validation_s", "planner_process_s",
           "total_s", "build", "image_version"]
NAME = re.compile(r"^custom_(\d+)_([A-Za-z]+)_(\d+)$")
TIMING = re.compile(r"^TIMING\s+stage=(\w+)\s+seconds=([0-9.eE+-]+)\s*$", re.M)
STATS = re.compile(r"^STATS\s+(.*)$", re.M)
OLD_LEN = re.compile(r"plan length (\d+)|Plan length:\s*(\d+)", re.I)
NEIGHBORS = re.compile(r"Neighbors visited[^0-9]*(\d+)", re.I)
SOLVER_STATS = re.compile(r"^STATS\s+search_seconds=\S+.*$", re.M)
STAGE_COLUMN = {"pddl_conversion": "pddl_conversion_s", "search": "search_s", "json_conversion": "json_conversion_s",
                "validation": "validation_s", "planner_process": "planner_process_s",
                "enhsp_process": "planner_process_s", "total": "total_s"}


def read_json(p):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def read_text(p):
    try:
        return p.read_text(errors="replace")
    except OSError:
        return ""


def parse_sacct(path):
    """{(array id, task index): {state, partition, node, maxrss_mb}} from `sacct -P -n` output."""
    out = {}
    for line in read_text(Path(path)).splitlines():
        f = line.split("|")
        if len(f) < 6:
            continue
        m = re.match(r"^(\d+)_(\d+)(\.\w+)?$", f[0])
        if not m or m[3] == ".extern":
            continue
        entry = out.setdefault((m[1], int(m[2])), {})
        if m[3] == ".batch":
            rss = parse_kb(f[4])
            if rss is not None:
                entry["maxrss_mb"] = round(rss / 1024, 1)
        else:
            entry.update(partition=f[1], node=f[2], state=f[5].split()[0].rstrip("+") if f[5] else "")
    return out


def parse_kb(text):
    m = re.match(r"^([0-9.]+)([KMGT]?)$", text.strip())
    if not m:
        return None
    return float(m[1]) * {"": 1, "K": 1, "M": 1024, "G": 1024 ** 2, "T": 1024 ** 3}[m[2]]


def tasks_of(run_dir):
    """[(index or None, instance, label, tool_dir)] from tasks.tsv, else from the folders present."""
    tsv = run_dir / "tasks.tsv"
    if tsv.exists():
        with open(tsv, newline="") as f:
            return [(int(r["index"]), r["instance"], "solver" if r["tool"] == "solver" else r["planner"],
                     run_dir / r["tool_dir"]) for r in csv.DictReader(f, delimiter="\t")]
    tasks = []
    for inst in sorted(p for p in run_dir.iterdir() if p.is_dir() and NAME.match(p.name)):
        for d in sorted(p for p in inst.iterdir() if p.is_dir()):
            if d.name == "local_search":
                seeds = sorted(s for s in d.glob("seed*") if (s / "result.json").exists())
                target = d if (d / "result.json").exists() else (seeds[0] if seeds else None)
                if target:
                    tasks.append((None, inst.name, "solver", target))
            elif d.name.startswith("planning") and (d / "result.json").exists():
                impl = read_json(d / "result.json").get("planner_impl")
                tasks.append((None, inst.name, impl or (d.name.split("-", 1)[1] if "-" in d.name else "planner"), d))
    return tasks


def has_scenario(d, instance):
    """Whether the generator produced this task's scenario (it can refuse, e.g. no room to park and service)."""
    return any((p / f"scenario_{instance}.json").exists() for p in (d.parent, d.parent.parent))


def classify(row, result, ev, sacct, scenario_exists=True):
    state = (sacct or {}).get("state", "")
    if not result and not scenario_exists:
        return "no_scenario"
    if not result:
        if state in ("OUT_OF_MEMORY", "OUT_OF_ME"):
            return "oom"
        return f"slurm_{state.lower()}" if state and state != "COMPLETED" else "no_result"
    if result.get("timed_out"):
        return "timeout"
    code = result.get("exit_code")
    if not result.get("plan_produced"):
        return "crash" if code not in (None, 0) else "no_plan"
    if row["valid"] is True:
        return "valid"
    return "invalid" if row["valid"] is False else "unevaluated"


def row_for(servicing, instance, label, d, sacct):
    m = NAME.match(instance)
    result, ev = read_json(d / "result.json"), read_json(d / "eval_result.json")
    row = dict.fromkeys(COLUMNS, "")
    row.update({"servicing": servicing, "runtime": result.get("wall_seconds", ""),
                "timed_out": result.get("timed_out", ""),
                "exit_code": "" if result.get("exit_code") is None else result["exit_code"],
                "plan_produced": result.get("plan_produced", ""), "image_version": result.get("image", "")})
    if m:
        row.update({"num_trains": int(m[1]), "matching-order": m[2], "instance-num": int(m[3])})
    if ev:
        row["valid"] = bool(ev.get("solved"))
        if not ev.get("solved"):
            row["reason"] = ev.get("reason", "")
    if sacct:
        row.update({k: sacct[k] for k in ("partition", "node", "maxrss_mb") if k in sacct})
        row["slurm_state"] = sacct.get("state", "")
    plan = read_json(d / "plan.json")
    if "actions" in plan:
        row["json_actions"] = len(plan["actions"])
    if label == "solver":
        row["type-solver"] = "solver"
        row["solution-length"] = row["json_actions"]
        out = read_text(d / "solver.out")
        n = NEIGHBORS.findall(out)
        row["solver_neighbors"] = n[-1] if n else ""
        stats = SOLVER_STATS.findall(out)
        if stats:  # newer solver images: one machine-readable line at the end of the search
            kv = dict(p.split("=", 1) for p in stats[-1].split()[1:] if "=" in p)
            row["solver_neighbors"] = kv.get("neighbors", row["solver_neighbors"])
            row["time_to_best_s"] = kv.get("time_to_best_seconds", "")
            row["solver_feasible"] = kv.get("feasible", "")
    else:
        row["type-solver"] = label
        out = read_text(d / "planner.out")
        for stage, secs in TIMING.findall(out):
            if stage in STAGE_COLUMN:
                row[STAGE_COLUMN[stage]] = float(secs)
        for line in STATS.findall(out):
            kv = dict(p.split("=", 1) for p in line.split() if "=" in p)
            row["expanded-states"] = kv.get("expanded", row["expanded-states"])
            row["pddl_plan_length"] = kv.get("plan_length", row["pddl_plan_length"])
        if row["pddl_plan_length"] == "":
            old = OLD_LEN.findall(out)
            if old:
                row["pddl_plan_length"] = next(x for x in old[-1] if x)
        row["solution-length"] = row["pddl_plan_length"]
    first = read_text(d / ("solver.out" if label == "solver" else "planner.err")).split("\n", 1)[0].strip()
    row["build"] = first if first.startswith(("HIP ", "robust-rail-planner")) else ""   # e.g. "HIP 2.2.0-edge+20261106.965fd71"
    row["outcome"] = classify(row, result, ev, sacct, has_scenario(d, instance))
    if row["outcome"] == "invalid" and not row["reason"]:
        row["reason"] = "see eval.out"
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="append", required=True, metavar="SERVICING=DIR[:ARRAYID,...]")
    ap.add_argument("--sacct", metavar="FILE", help="sacct -P -n output, see the module docstring")
    ap.add_argument("-o", "--output", required=True)
    args = ap.parse_args()
    sacct = parse_sacct(args.sacct) if args.sacct else {}
    rows = []
    for spec in args.run:
        servicing, _, rest = spec.partition("=")
        path, _, ids = rest.partition(":")
        array_ids = [i for i in ids.split(",") if i]
        for idx, instance, label, d in tasks_of(Path(path)):
            info = next((sacct[(a, idx)] for a in array_ids if (a, idx) in sacct), None)
            rows.append(row_for(servicing, instance, label, d, info))
    rows.sort(key=lambda r: (r["servicing"], r["type-solver"], r["num_trains"], r["matching-order"], r["instance-num"]))
    with open(args.output, "w", newline="") as f:
        w = csv.DictWriter(f, COLUMNS)
        w.writeheader()
        w.writerows(rows)
    counts = {}
    for r in rows:
        counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
    print(f"{len(rows)} rows -> {args.output}  outcomes: {counts}", file=sys.stderr)


if __name__ == "__main__":
    main()
