#!/usr/bin/env python3
"""Render a plan (from the solver or the planner) as an HTML visualisation.

    run_visualizer.py example2

finds plans/plan_example2.json and scenarios/scenario_example2.json in the
Location_* directory holding them, runs the sibling robust-rail-visualizer
checkout's visualize_plan.py on them, writes plans/plan_example2.html next to
the plan, and opens it in the browser.

Unlike the other run_*.py scripts this needs no container: the visualizer is
plain Python run from its own checkout.
"""

import argparse
import re
import subprocess
import sys
import webbrowser
from pathlib import Path

from scripts.instance_filter import ensure_single, instance_of, select

ROOT = Path(__file__).parent
PLAN_PREFIX = "plan_"
DEFAULT_VISUALIZER_DIR = ROOT.parent / "robust-rail-visualizer"


def layout_name(location_dir: Path) -> str:
    """Visualizer layout file stem for a location: Location_KleineBinckhorst -> kleine_binckhorst."""
    name = location_dir.name.removeprefix("Location_")
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()


def find_plans(locations: list[Path]) -> list[Path]:
    return [p for loc in locations for p in sorted((loc / "plans").glob(f"{PLAN_PREFIX}*.json"))]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("instance", nargs="?", metavar="NAME",
                        help="Instance to visualise: plans/plan_<NAME>.json (a pasted filename or "
                             "a wildcard works, but it must select exactly one plan).")
    parser.add_argument("--single", metavar="NAME", help="Same as the positional NAME.")
    parser.add_argument("--location", metavar="NAME",
                        help="Restrict to a single Location_* directory.")
    parser.add_argument("--layout", type=Path, metavar="FILE",
                        help="Visualizer layout JSON (default: <visualizer-dir>/layouts/"
                             "<location in snake_case>.json).")
    parser.add_argument("--visualizer-dir", type=Path, default=DEFAULT_VISUALIZER_DIR,
                        help=f"robust-rail-visualizer checkout (default: {DEFAULT_VISUALIZER_DIR}).")
    parser.add_argument("--no-open", action="store_true",
                        help="Do not open the result in the browser.")
    args = parser.parse_args()

    if args.instance and args.single:
        parser.error("Give the instance either positionally or with --single, not both.")
    instance = args.instance or args.single
    if not instance:
        parser.error("Name an instance, e.g. run_visualizer.py example2.")

    if args.location:
        locations = [ROOT / args.location]
        if not locations[0].is_dir():
            parser.error(f"No such location: {locations[0]}")
    else:
        locations = sorted(ROOT.glob("Location_*/"))
    ensure_single(find_plans(locations), instance, PLAN_PREFIX, "instance")
    plan = select(find_plans(locations), instance, PLAN_PREFIX)[0]
    location_dir = plan.parent.parent
    suffix = instance_of(plan, PLAN_PREFIX)

    scenario = location_dir / "scenarios" / f"scenario_{suffix}.json"
    if not scenario.is_file():
        sys.exit(f"ERROR: no scenario for this plan: {scenario} does not exist.")

    script = args.visualizer_dir / "visualize_plan.py"
    if not script.is_file():
        sys.exit(f"ERROR: {script} not found; pass --visualizer-dir.")
    layout = args.layout or args.visualizer_dir / "layouts" / f"{layout_name(location_dir)}.json"
    if not layout.is_file():
        sys.exit(f"ERROR: layout {layout} not found; pass --layout.")

    output = plan.with_suffix(".html")
    cmd = [sys.executable, str(script.resolve()),
           "--location", str((location_dir / "location.json").resolve()),
           "--scenario", str(scenario.resolve()),
           "--plan", str(plan.resolve()),
           "--layout", str(layout.resolve()),
           "--output", str(output.resolve())]
    # cwd is the visualizer's: it may load assets relative to itself.
    result = subprocess.run(cmd, cwd=args.visualizer_dir)
    if result.returncode != 0:
        sys.exit(result.returncode)

    print(f"Wrote {output}")
    if not args.no_open:
        webbrowser.open(output.resolve().as_uri())


if __name__ == "__main__":
    main()
