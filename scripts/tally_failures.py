#!/usr/bin/env python3
"""Break a run_experiment.py results directory down by failure message.

`report_results.py` answers "how many solved?"; this answers "and why did the
rest not?", by collapsing each instance's outcome into a message family and
listing the distinguishing part per instance:

    python3 scripts/tally_failures.py results/kb_42_20260917_101500

Each instance's verdict comes from <instance>/<tool>/eval_result.json's
"reason", except the departure-mismatch family, which the evaluator reports on
stderr rather than in the verdict, so eval.err is consulted for those.

--tool solver/planner restricts to one tool's eval_result.json files; --output
writes the report to a file instead of stdout -- run_experiment.py drives both
together (once per tool) after every attempt, so
tally_failures_solver.txt/tally_failures_planner.txt fill in live alongside
runs.csv/feasibility.csv, the same results directory this script always read.
"""

import argparse
import collections
import glob
import json
import os
import re
import sys
from pathlib import Path

# Matches run_experiment.py's own FOLDER_NAMES -- kept as its own copy here
# rather than imported, the same way report_results.py's TOOL_FOLDERS is its
# own copy: this script is meant to also run standalone, by hand, against a
# results directory, not only as a subprocess run_experiment.py drives.
TOOL_FOLDER = {"solver": "local_search", "planner": "planning"}


def classify(reason: str | None, err: str) -> tuple[str, str | None]:
    """Return (message family, per-instance detail) for one instance."""
    reason = reason or ""
    if not reason:
        return "valid", None
    if reason.startswith("The length of the"):
        m = re.search(r"train \[(\d+)\]: ([\d.]+).*?:([\d.]+)", reason)
        return ("scenario rejected: train longer than its track",
                f"train {m.group(1)}: {float(m.group(2)):.2f} m > {float(m.group(3)):.0f} m" if m else None)
    if reason.startswith(("The number of departure trains", "More trains of type")):
        m = re.search(r"\[(.+?)\]", reason)
        return ("scenario rejected: per-type train counts",
                f"type {m.group(1)}" if m else None)
    m = re.search(r"to Track (\S+) exceeds the maximum length \(([\d.]+) > ([\d.]+)\)", reason)
    if m:
        return ("plan: track overfilled",
                f"track {m.group(1)}: {float(m.group(2)):.2f} m > {float(m.group(3)):.0f} m")
    m = re.search(r"(ShuntingUnit-\S+) cannot leave Track (\S+)", reason)
    if m:
        return "plan: unit cannot leave its track", f"track {m.group(2)}"
    if "is reserved" in reason or "is occupied" in reason:
        return "plan: track already in use", reason
    if reason == "plan rejected":
        if "departure mismatch" in err:
            return ("plan: departure time mismatch",
                    f"{err.count('Error Suspected')} train(s) flagged")
        if "unordered_map" in err:
            return "evaluator crash: unordered_map::at", None
        first = next((line.strip() for line in err.splitlines() if line.strip()), "")
        return f"plan rejected, unclassified: {first[:60]}", None
    return reason[:70], None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("results_dir", help="the --output-dir a run_experiment.py run wrote to")
    parser.add_argument("--tool", choices=["solver", "planner"],
                        help="Restrict to one tool's eval_result.json files (run_experiment.py's "
                             "local_search/ or planning/ folder) instead of both.")
    parser.add_argument("--output", type=Path, metavar="FILE",
                        help="Write the report to this file instead of stdout. Also changes what "
                             "an empty result set means: without --output that is a hard error (a "
                             "human pointed this at a directory expecting a report), but with it, "
                             "\"0 instances\" is written and the script exits 0 -- the case "
                             "run_experiment.py hits calling this after every attempt from the "
                             "start of a sweep, long before any --tool has a result yet.")
    parser.add_argument("--quiet", action="store_true", help="counts only, without the per-instance lines")
    args = parser.parse_args()

    folder = TOOL_FOLDER[args.tool] if args.tool else "*"
    rows = []
    for path in sorted(glob.glob(os.path.join(args.results_dir, "*", folder, "eval_result.json"))):
        result = json.load(open(path))
        err_path = os.path.join(os.path.dirname(path), "eval.err")
        err = open(err_path).read() if os.path.exists(err_path) else ""
        family, detail = classify(result.get("reason"), err)
        rows.append((result["instance"], family, detail))

    out = open(args.output, "w") if args.output else sys.stdout
    try:
        if not rows:
            if args.output:
                print("0 instances", file=out)
                return
            tool_note = f" for --tool {args.tool}" if args.tool else ""
            raise SystemExit(f"no eval_result.json found under {args.results_dir}{tool_note}")

        counts = collections.Counter(family for _, family, _ in rows)
        print(f"{len(rows)} instances\n", file=out)
        for family, n in counts.most_common():
            print(f"{n:>3}  {family}", file=out)
            if not args.quiet:
                for instance, f, detail in rows:
                    if f == family and detail:
                        print(f"       {instance:<24} {detail}", file=out)
    finally:
        if args.output:
            out.close()


if __name__ == "__main__":
    main()
