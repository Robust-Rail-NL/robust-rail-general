#!/usr/bin/env python3
"""Validate the fixtures in this repo against the generator's exported schemas.

SKETCH — not yet wired into the pipeline. Two things are unresolved, both noted
in docs/roadmap-2.0.0.md under Phase 3c:

  * Where the schemas come from. This reads them from a generator checkout via
    --schema-dir, which couples the repos. Publishing them as a release artifact
    alongside the images is probably the better answer.
  * Nothing here checks that the generator's committed schemas still match its
    Pydantic models. Validating against a stale schema is worse than not
    validating, because it looks like it passed.

scenario_config_*.json is deliberately not covered: there is no schema for it.
It is checked by the generator's check_config.py, which is a list of presence
checks and rejects nothing it does not recognise — which is what lets the
configurations carry their "intent" blocks. A schema written for them would have
to permit those.

Usage:
    ./validate_json.py --schema-dir ../robust-rail-generator/schema
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent

# Which schema validates which fixtures, relative to a Location_* directory.
FIXTURE_SCHEMAS = {
    "location.json": "schema_location.json",
    "scenarios/scenario_*.json": "schema_scenario.json",
    "plans/plan_*.json": "schema_plan.json",
}


def _load_validator(schema_path: Path):
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        sys.exit(
            "jsonschema is not installed. It is the only dependency this script has:\n"
            "    pip install jsonschema"
        )
    schema = json.loads(schema_path.read_text())
    return Draft202012Validator(schema)


def _validate(path: Path, validator) -> list[str]:
    try:
        instance = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return [f"not valid JSON: {exc}"]
    # Sorted by path so the output is stable enough to diff between runs.
    return [
        f"{'/'.join(str(p) for p in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--schema-dir", required=True, type=Path,
                        help="Directory holding schema_location.json and friends.")
    parser.add_argument("--location", metavar="NAME",
                        help="Restrict to a single Location_* directory.")
    parser.add_argument("--max-errors", type=int, default=5,
                        help="Errors to show per file before truncating (default: 5).")
    args = parser.parse_args()

    validators = {}
    for schema_name in set(FIXTURE_SCHEMAS.values()):
        schema_path = args.schema_dir / schema_name
        if not schema_path.exists():
            sys.exit(f"No such schema: {schema_path}")
        validators[schema_name] = _load_validator(schema_path)

    locations = [ROOT / args.location] if args.location else sorted(ROOT.glob("Location_*/"))
    checked = failed = 0

    for location in locations:
        for pattern, schema_name in FIXTURE_SCHEMAS.items():
            for path in sorted(location.glob(pattern)):
                checked += 1
                errors = _validate(path, validators[schema_name])
                if not errors:
                    continue
                failed += 1
                print(f"\n{path.relative_to(ROOT)}  ({schema_name})")
                for error in errors[: args.max_errors]:
                    print(f"    {error}")
                if len(errors) > args.max_errors:
                    print(f"    ... and {len(errors) - args.max_errors} more")

    print(f"\n{checked - failed}/{checked} files valid")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
