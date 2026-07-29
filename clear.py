#!/usr/bin/env python3
"""Remove generated plans, evaluations, and scenarios."""

import argparse
import sys
from pathlib import Path


SCENARIO_PLANNING_INPUTS_DIR = Path(__file__).resolve().parent
EMPTY_DIRS = ["evaluations", "plans", "scenarios"]


def _delete(path: Path, dry_run: bool) -> None:
    print(f"  rm {path.relative_to(SCENARIO_PLANNING_INPUTS_DIR)}")
    if not dry_run:
        path.unlink()


def _clear_location(loc: Path, dry_run: bool) -> int:
    removed = 0

    for dirname in EMPTY_DIRS:
        dir_path = loc / dirname
        if not dir_path.is_dir():
            continue
        for item in sorted(dir_path.iterdir()):
            if item.is_file():
                _delete(item, dry_run)
                removed += 1

    return removed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Empty the evaluations, plans, and scenarios folders."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be removed without deleting anything.")
    parser.add_argument("--location", metavar="NAME",
                        help="Restrict to a single Location_* directory.")
    args = parser.parse_args()

    locations = [SCENARIO_PLANNING_INPUTS_DIR / args.location] if args.location \
        else sorted(SCENARIO_PLANNING_INPUTS_DIR.glob("Location_*/"))

    total = 0
    for loc in locations:
        if not loc.is_dir():
            print(f"WARNING: {loc} not found, skipping.", file=sys.stderr)
            continue
        print(f"\n{loc.name}")
        total += _clear_location(loc, args.dry_run)

    verb = "Would remove" if args.dry_run else "Removed"
    print(f"\n{verb} {total} file(s).")


if __name__ == "__main__":
    main()
