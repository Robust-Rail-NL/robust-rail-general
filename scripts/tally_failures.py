#!/usr/bin/env python3
"""Break a run_experiment.py results directory down by failure message.

`report_results.py` answers "how many solved?"; this answers "and why did the
rest not?", by collapsing each instance's outcome into a message family and
listing the distinguishing part per instance:

    python3 scripts/tally_failures.py results/kb_42_20260917_101500

Each instance's verdict comes from <instance>/<tool>/eval_result.json's
"reason", except the departure-mismatch family, which the evaluator reports on
stderr rather than in the verdict, so eval.err is consulted for those.
"""

import argparse
import collections
import glob
import json
import os
import re


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
    parser.add_argument("--quiet", action="store_true", help="counts only, without the per-instance lines")
    args = parser.parse_args()

    rows = []
    for path in sorted(glob.glob(os.path.join(args.results_dir, "*", "*", "eval_result.json"))):
        result = json.load(open(path))
        err_path = os.path.join(os.path.dirname(path), "eval.err")
        err = open(err_path).read() if os.path.exists(err_path) else ""
        family, detail = classify(result.get("reason"), err)
        rows.append((result["instance"], family, detail))

    if not rows:
        raise SystemExit(f"no eval_result.json found under {args.results_dir}")

    counts = collections.Counter(family for _, family, _ in rows)
    print(f"{len(rows)} instances\n")
    for family, n in counts.most_common():
        print(f"{n:>3}  {family}")
        if not args.quiet:
            for instance, f, detail in rows:
                if f == family and detail:
                    print(f"       {instance:<24} {detail}")


if __name__ == "__main__":
    main()
