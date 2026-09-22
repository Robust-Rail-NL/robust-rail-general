#!/usr/bin/env python3
"""The experiment JSON: the one file that describes a run.

Top level holds the experiment's own settings — what it is called, which
location, which tools, what budget. "scenarios" holds the generation sweep that
generate_experiment_configs.py expands into scenario_config_*.json files:

    {
      "name": "baseline_sweep",
      "location": "Location_KleineBinckhorst",
      "tools": ["solver", "planner"],
      "max_duration": 600,
      "scenarios": {"number_of_trains": [5, 10, 15], ...}
    }

"name" is what the run is called, and it is the only name a run needs: configs
land in <location>/configurations/<name>/ and results in results/<name>/.

run_experiment.py takes no settings of its own — it runs what the file says, so
the file is an exact record of the run. load() therefore fills in every default
and does every check here, leaving its caller nothing to resolve.

The "scenarios" block is returned unvalidated: its keys belong to
generate_experiment_configs.py's own DEFAULTS, and that script checks them when
it reads the same file. Validating them here would mean importing it, and it
already imports this.
"""

import json
from pathlib import Path

SCENARIOS_KEY = "scenarios"
VERSIONS_KEY = "versions"

TOOLS = ("solver", "planner")
PLANNERS = ("symbolic", "symbolic-rail", "enhsp")
VERSION_KEYS = ("generator", "solver", "planner", "evaluator")
DEFAULT_VERSION = "edge"

REQUIRED_KEYS = ("name", "location")

# Optional top-level settings and the value used when the file omits them.
# None means the behaviour is "unset" rather than a number: no wall-clock
# budget, no seed override, no fixed certification threshold.
OPTIONAL_DEFAULTS = {
    "tools": list(TOOLS),
    "planner": "symbolic-rail",
    "max_duration": None,
    "seed": None,
    "num_seeds": None,
    "certify_threshold": None,
    "jobs": 1,
}


class SpecError(ValueError):
    """An experiment JSON that cannot be run, with a message meant to be shown as-is."""


def _check_keys(found: set, allowed, where: str, path: Path) -> None:
    unknown = found - set(allowed)
    if unknown:
        raise SpecError(f"Unknown {where} key(s) in {path}: {sorted(unknown)}. "
                        f"Known: {sorted(allowed)}")


def _check_settings(spec: dict, path: Path) -> None:
    bad_tools = [t for t in spec["tools"] if t not in TOOLS]
    if bad_tools or not spec["tools"]:
        raise SpecError(f'"tools" in {path} must be a non-empty subset of {list(TOOLS)}, '
                        f"got {spec['tools']}")
    if spec["planner"] not in PLANNERS:
        raise SpecError(f'"planner" in {path} must be one of {list(PLANNERS)}, '
                        f"got {spec['planner']!r}")
    if spec["jobs"] < 1:
        raise SpecError(f'"jobs" in {path} must be at least 1, got {spec["jobs"]}')
    if spec["seed"] is not None and spec["num_seeds"] is not None:
        raise SpecError(f'"seed" and "num_seeds" in {path} are mutually exclusive: '
                        f"one fixed seed, or a sweep over several.")
    if spec["num_seeds"] is not None:
        if spec["num_seeds"] < 1:
            raise SpecError(f'"num_seeds" in {path} must be at least 1, got {spec["num_seeds"]}')
        if "solver" not in spec["tools"]:
            raise SpecError(f'"num_seeds" in {path} applies to the solver, which "tools" excludes.')


def load(path: Path) -> dict:
    """Parse, validate and fill in an experiment JSON.

    Raises SpecError (a ValueError) with a message meant to be shown as-is.
    Every optional setting is present in the result, as is "versions" (one
    entry per tool) and "scenarios" (empty if the file omitted it).
    """
    with open(path) as f:
        spec = json.load(f)
    if not isinstance(spec, dict):
        raise SpecError(f"{path} must contain a JSON object, not a {type(spec).__name__}.")

    allowed = REQUIRED_KEYS + tuple(OPTIONAL_DEFAULTS) + (VERSIONS_KEY, SCENARIOS_KEY)
    _check_keys(set(spec), allowed, "top-level", path)
    missing = [k for k in REQUIRED_KEYS if not spec.get(k)]
    if missing:
        raise SpecError(f"{path} is missing required key(s): {missing}")

    for key, fallback in OPTIONAL_DEFAULTS.items():
        if spec.get(key) is None:
            spec[key] = fallback

    versions = spec.get(VERSIONS_KEY) or {}
    _check_keys(set(versions), VERSION_KEYS, f'"{VERSIONS_KEY}"', path)
    spec[VERSIONS_KEY] = {k: versions.get(k, DEFAULT_VERSION) for k in VERSION_KEYS}
    spec[SCENARIOS_KEY] = spec.get(SCENARIOS_KEY) or {}

    _check_settings(spec, path)
    return spec
