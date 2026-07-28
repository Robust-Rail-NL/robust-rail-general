#!/usr/bin/env python3
"""Run the full generator → solver → evaluator pipeline."""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
ALL_STEPS = ["generator", "solver", "evaluator"]
SCRIPTS = {
    "generator": ROOT / "run_generator.py",
    "solver": ROOT / "run_solver.py",
    "evaluator": ROOT / "run_evaluator.py",
}


def _run_step(step: str, extra_args: list[str]) -> bool:
    script = SCRIPTS[step]
    cmd = [sys.executable, str(script)] + extra_args
    print(f"\n{'='*60}")
    print(f"  Step: {step}")
    print(f"{'='*60}")
    result = subprocess.run(cmd)
    return result.returncode == 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the full generator → solver → evaluator pipeline."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Pass --dry-run to each step.")
    parser.add_argument("--location", metavar="NAME",
                        help="Restrict to a single Location_* directory.")
    parser.add_argument("--version", choices=['protobuf', 'pydantic', 'local'], default='protobuf',
                        help="Pick a docker image version ('local' is reserved for locally built images).")
    parser.add_argument("--steps", metavar="STEPS",
                        default=",".join(ALL_STEPS),
                        help=f"Comma-separated list of steps to run (default: {','.join(ALL_STEPS)}).")
    args = parser.parse_args()

    steps = [s.strip() for s in args.steps.split(",")]
    unknown = [s for s in steps if s not in ALL_STEPS]
    if unknown:
        print(f"ERROR: unknown step(s): {', '.join(unknown)}. Valid: {', '.join(ALL_STEPS)}", file=sys.stderr)
        sys.exit(1)

    extra: list[str] = []
    if args.dry_run:
        extra.append("--dry-run")
    extra += ["--version", args.version]
    if args.location:
        extra += ["--location", args.location]

    for step in steps:
        if not _run_step(step, extra):
            print(f"\nPipeline aborted: step '{step}' failed.", file=sys.stderr)
            sys.exit(1)

    print(f"\nPipeline complete: {' → '.join(steps)}")


if __name__ == "__main__":
    main()
