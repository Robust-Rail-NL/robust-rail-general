"""Migrate scenario fixtures to the head-first unit-order convention.

Unit lists (`in[].members`, `out[].trainUnits`) are read head-first: index 0 is the unit that
leads the train. See docs/unit-order-convention.md and issue #50. Older fixtures were generated
with a departing list identical to the arrival list. A train that leaves at the end of the yard
its units arrived at drives out with the other end leading, so its head-first list is the
reverse. The generator applies the same rule (RandomGenerator.should_reverse_units).

A fixture file does not record which arriving train a departing unit came from, so the rule is
applied only where that does not matter:

- A location whose gateways all lie at one end of the yard (Kleine Binckhorst): every departing
  train with more than one unit is reversed, if the scenario has no standing trains.
- A location with gateways at several ends: only scenarios without multi-unit departing trains
  qualify (nothing to reverse).

Every other scenario is reported as needing a manual decision and left alone. Plans and
evaluation outputs next to a migrated scenario describe the old reading and have to be produced
again; they are listed, not touched.

The script is NOT idempotent: running it twice on a file undoes the migration. It is a dry run
unless --write is given, and --write refuses to touch a file with uncommitted changes, so git
history is the record of what was migrated.

    python3 scripts/migrate_unit_order.py              # dry run over all tracked scenario files
    python3 scripts/migrate_unit_order.py --write
    python3 scripts/migrate_unit_order.py PATH...      # only these files
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def gateway_end(parts: dict, gateway_id: int, bumper_id: int) -> tuple:
    """The end of the yard a gateway is on: the track parts on its side away from the bumper
    (mirrors RandomGenerator.gateway_end in robust-rail-generator)."""
    gateway = parts[gateway_id]
    if bumper_id in gateway["aSide"]:
        end = gateway["bSide"]
    elif bumper_id in gateway["bSide"]:
        end = gateway["aSide"]
    else:
        end = []
    if not end:
        raise ValueError(f"cannot tell which end of the yard gateway {gateway_id} (bumper {bumper_id}) is on")
    return tuple(end)


def load_location(location_dir: Path) -> dict:
    return {p["id"]: p for p in json.loads((location_dir / "location.json").read_text())["trackParts"]}


def plan(scenario: dict, parts: dict):
    """Return (action, detail): action is 'reverse' (with the departing trains to reverse),
    'nothing' or 'manual'."""
    ends = {gateway_end(parts, t["firstParkingTrackPart"], t["entryTrackPart"]) for t in scenario["in"]}
    ends |= {gateway_end(parts, t["lastParkingTrackPart"], t["leaveTrackPart"]) for t in scenario["out"]}
    multi_out = [t for t in scenario["out"] if len(t["trainUnits"]) > 1]
    if not multi_out:
        return "nothing", "no departing train with more than one unit"
    if scenario["inStanding"] or scenario["outStanding"]:
        return "manual", "has standing trains: the source of each departing unit is not recorded"
    if len(ends) != 1:
        return "manual", f"gateways at {len(ends)} ends of the yard: the arrival end of each unit is not recorded"
    return "reverse", multi_out


def tracked_scenarios() -> list[Path]:
    out = subprocess.check_output(["git", "ls-files", "Location_*/*.json", "Location_*/**/*.json"], cwd=REPO, text=True)
    return [REPO / f for f in out.split() if Path(f).name.startswith("scenario")]


def has_uncommitted_changes(path: Path) -> bool:
    return bool(subprocess.check_output(["git", "status", "--porcelain", "--", str(path)], cwd=REPO, text=True))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="*", type=Path)
    ap.add_argument("--write", action="store_true", help="rewrite the files (default: dry run)")
    args = ap.parse_args()
    paths = [p.resolve() for p in args.paths] or tracked_scenarios()

    locations: dict[Path, dict] = {}
    counts = {"reverse": 0, "nothing": 0, "manual": 0, "skipped": 0}
    for path in paths:
        text = path.read_text()
        scenario = json.loads(text)
        if not isinstance(scenario, dict) or "in" not in scenario or "trainUnitTypes" not in scenario:
            continue  # a configuration, plan or other file
        rel = path.relative_to(REPO)
        location_dir = REPO / rel.parts[0]
        if not (location_dir / "location.json").exists():
            print(f"skip    {rel}: no location.json in {rel.parts[0]}")
            counts["skipped"] += 1
            continue
        parts = locations.setdefault(location_dir, load_location(location_dir))
        if json.dumps(scenario, indent=4, ensure_ascii=False) + "\n" != text:
            print(f"skip    {rel}: not formatted as json.dumps(indent=4); rewriting would churn the file")
            counts["skipped"] += 1
            continue
        action, detail = plan(scenario, parts)
        counts[action] += 1
        if action != "reverse":
            print(f"{action:7} {rel}: {detail}")
            continue
        for train in detail:
            train["trainUnits"].reverse()
        if json.dumps(scenario, indent=4, ensure_ascii=False) + "\n" == text:
            # Departing units carry no id, so a list of units of identical type reads the same reversed.
            counts["reverse"] -= 1
            counts["nothing"] += 1
            print(f"nothing {rel}: reversing changes no departing list (units of one type)")
            continue
        print(f"reverse {rel}: {len(detail)} departing train(s)")
        if args.write:
            if has_uncommitted_changes(path):
                print(f"        refusing to write {rel}: uncommitted changes")
                counts["skipped"] += 1
                continue
            path.write_text(json.dumps(scenario, indent=4, ensure_ascii=False) + "\n")
        stem = path.stem.removeprefix("scenario_")
        stale = sorted(p.name for p in path.parent.glob(f"*{stem}*") if p != path and p.suffix in (".json", ".txt", ".out"))
        stale += sorted(
            str(p.relative_to(REPO))
            for p in (location_dir / "plans").glob(f"*{stem}*")
        ) if (location_dir / "plans").is_dir() else []
        if stale:
            print(f"        stale next to it (made for the old reading): {', '.join(stale)}")
    print(f"\n{'written' if args.write else 'dry run'}: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
