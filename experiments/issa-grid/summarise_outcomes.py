#!/usr/bin/env python3
"""Count run outcomes per (servicing, tool, number of trains) from the CSV made by extract_csv.py.

usage: summarise_outcomes.py issa_grid.csv [--by-matching]

One line per cell: how many runs ended valid / invalid / timeout / oom / crash / no_plan, and how many are not
finished (no_result, slurm_*) or cannot exist (no_scenario). A tool that is `valid` for no instance of a size
will not be `valid` for larger ones either, which is what decides whether stage 2 is worth its CPU hours.
"""
import csv
import sys
from collections import Counter, defaultdict

ORDER = ["valid", "invalid", "timeout", "oom", "crash", "no_plan", "unevaluated"]
path = sys.argv[1]
by_matching = "--by-matching" in sys.argv
cells = defaultdict(Counter)
for r in csv.DictReader(open(path)):
    key = (r["servicing"], r["type-solver"], int(r["num_trains"] or 0), r["matching-order"] if by_matching else "")
    o = r["outcome"]
    cells[key][o if o in ORDER or o == "no_scenario" else "unfinished"] += 1

print(f"{'servicing':9} {'tool':14} {'trains':>6} {'match':>6}  " + "  ".join(f"{k:>10}" for k in ORDER + ["unfinished", "no_scenario"]))
for key in sorted(cells):
    c = cells[key]
    total = sum(c.values())
    print(f"{key[0]:9} {key[1]:14} {key[2]:>6} {key[3]:>6}  " + "  ".join(f"{c[k]:>10}" for k in ORDER + ["unfinished", "no_scenario"])
          + f"   (n={total})")
