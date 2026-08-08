#!/usr/bin/env python3
"""Validate the fixtures in this repo against the generator's exported schemas.

Run by .github/workflows/validate-fixtures.yml, which gates on it. The schemas
come from a generator checkout via --schema-dir; where they should ultimately be
published is recorded in docs/roadmap-2.0.0.md under Phase 3c, along with why
that workflow also re-exports them and fails if they have gone stale.

Covers location.json, scenarios/, plans/ and configurations/. The last of those
is generator input rather than interchange, and the only input written by hand
rather than generated — which is why it is worth validating: check_config.py
checks that required keys are present but accepts anything it does not
recognise, so a mistyped optional key simply never takes effect.

Usage:
    ./validate_json.py --schema-dir ../robust-rail-generator/schema
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent

# Which schema validates which fixtures, relative to a Location_* directory.
#
# fixtures/ holds the classified corpus written by `sweep_seeds.py --save`, filed
# under feasible/, infeasible/ and unresolved/. Those are checked in and outlive
# the run that produced them, so they are worth validating for the same reason
# the working scenarios and plans are — more so, since a feasible fixture's plan
# is evidence that the scenario can be planned at all, and evidence in a format
# nothing can read any more is not evidence.
FIXTURE_SCHEMAS = {
    "location.json": "schema_location.json",
    "scenarios/scenario_*.json": "schema_scenario.json",
    "plans/plan_*.json": "schema_plan.json",
    "configurations/scenario_config_*.json": "schema_scenario_config.json",
    "fixtures/*/scenario_*.json": "schema_scenario.json",
    "fixtures/*/plan_*.json": "schema_plan.json",
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


def _branch_for(error) -> Optional[int]:
    """Index of the oneOf branch a discriminated union meant to take.

    jsonschema has no notion of `discriminator` — it is an OpenAPI keyword, not
    a JSON Schema one — so a union failure is reported against every branch at
    once. For scenario_config that means a single mistyped key in the
    trains_given=false form is reported as eight unexpected keys against the
    trains_given=true form, which is worse than useless. The schema does publish
    the discriminator, so use it to say which branch was actually intended.
    """
    schema = error.schema
    if not isinstance(schema, dict):
        return None
    discriminator = schema.get("discriminator")
    if not discriminator or "oneOf" not in schema:
        return None
    if not isinstance(error.instance, dict):
        return None
    value = error.instance.get(discriminator.get("propertyName"))
    if value is None:
        return None
    target = discriminator.get("mapping", {}).get(str(value))
    for index, branch in enumerate(schema["oneOf"]):
        if isinstance(branch, dict) and branch.get("$ref") == target:
            return index
    return None


def _describe(error) -> str:
    """One line for an error, descending into anyOf/oneOf where it helps.

    A failure against a union reports only "is not valid under any of the given
    schemas", which names the branch point rather than the mistake. The real
    errors are in error.context: prefer the branch the discriminator selects,
    and otherwise let best_match guess.
    """
    from jsonschema.exceptions import best_match

    if error.context:
        candidates = list(error.context)
        branch = _branch_for(error)
        if branch is not None:
            on_branch = [e for e in candidates if list(e.schema_path)[:1] == [branch]]
            candidates = on_branch or candidates
        specific = best_match(candidates)
        if specific is not None:
            # absolute_path is relative to the instance root, not to the error it
            # came from: a context error's parent is the union error, and
            # absolute_path walks up through it. Prefixing error.absolute_path
            # here would repeat the path rather than complete it.
            return f"{'/'.join(str(p) for p in specific.absolute_path) or '<root>'}: {specific.message}"
    return f"{'/'.join(str(p) for p in error.absolute_path) or '<root>'}: {error.message}"


def _validate(path: Path, validator) -> list[str]:
    try:
        instance = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return [f"not valid JSON: {exc}"]
    # Sorted by path so the output is stable enough to diff between runs.
    return [
        _describe(error)
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
