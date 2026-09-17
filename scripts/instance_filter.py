#!/usr/bin/env python3
"""Single-instance selection for the run_generator/run_solver/run_evaluator/run_planner scripts.

Every step globs a family of files whose names encode one instance as a
suffix:

    configurations/scenario_config_<suffix>.json   generator input
    scenarios/scenario_<suffix>.json               generator output -> solver/planner input
    plans/plan_<suffix>.json                       solver/planner output -> evaluator input

--instance filters on that suffix, so a step can run one instance instead of
sweeping every file in the location.

The suffix is the same at every step, and that is deliberate rather than
automatic: run_generator.py passes --scenario-file explicitly, because left
to itself the generator names its output after the location, train count and
seed instead (see the comment on that argument). One --instance value
therefore selects the same instance from any of the four steps.

Wildcards are accepted on top of that, for selecting a group in one run —
'marginal_*' for both marginal fixtures, '*_s7' for one seed across a sweep.
"""

import fnmatch
import sys
from collections.abc import Iterable
from pathlib import Path


def instance_of(path: Path, prefix: str) -> str:
    """The instance suffix encoded in one step input's filename."""
    return path.stem.removeprefix(prefix)


def _normalize(instance: str, prefix: str) -> str:
    """Accept a pasted filename ('scenario_foo.json') as well as a bare suffix ('foo').

    Copying a name straight out of `ls` is the obvious thing to try, and
    rejecting it would only mean retyping the same string with both ends
    trimmed. Patterns survive the trimming unchanged unless they spell out
    the parts being trimmed ('scenario_*.json' -> '*'), which selects the
    same files either way.
    """
    return instance.removesuffix(".json").removeprefix(prefix)


def select(paths: Iterable[Path], instance: str | None, prefix: str) -> list[Path]:
    """Filter step inputs down to one instance; `None` keeps all of them.

    Matching is against the filename suffix and honours shell-style
    wildcards. fnmatchcase rather than fnmatch: the fixture names are
    mixed-case (KleineBinckhorst_*), and plain fnmatch would fold case on
    Windows — which these scripts support — and not on macOS or Linux,
    making the same --instance select differently per platform.
    """
    paths = list(paths)
    if instance is None:
        return paths
    wanted = _normalize(instance, prefix)
    return [p for p in paths if fnmatch.fnmatchcase(instance_of(p, prefix), wanted)]


def fail_no_match(instance: str, available: Iterable[str]) -> None:
    """Exit non-zero, listing what was there instead. Never returns.

    A mistyped --instance would otherwise filter down to nothing and report
    "Done: 0/0 succeeded" with exit 0 — indistinguishable from a clean run,
    which is the same trap run_planner.py's empty-sweep warning exists to
    cover. Loud here, because the whole point of --instance is that the user
    named something they expected to exist.
    """
    names = sorted(set(available))
    print(f"\nERROR: --instance {instance!r} matched no files.", file=sys.stderr)
    if names:
        print("Available instances:", file=sys.stderr)
        for name in names:
            print(f"  {name}", file=sys.stderr)
        print("Wildcards are accepted, e.g. --instance '*marginal_congestion'.", file=sys.stderr)
    else:
        print("No candidate files exist here at all — check --location, and that the "
              "previous pipeline step actually ran.", file=sys.stderr)
    sys.exit(1)
