#!/bin/bash
# Condition (a): one direct apptainer invocation of the planner, with real
# phase timestamps (see scripts/cold_start_probe/run_planner_direct.py for
# why this bypasses run_planner.py entirely).
#
# Doubles as the "is the cache cold yet" canary to run before each of the
# other conditions: a sub-45s total here means it's still warm (matches the
# poster sweeps' own "slow" threshold) -- wait longer and re-check. Over 45s
# means it's cold enough to proceed with the condition that follows.
#
# Submit from the repo root with:
#   sbatch scripts/cold_start_probe/planner-timing-single.sbatch <SCENARIO.json> <OUT_DIR> [CONDITION]
# CONDITION (default "single") is just a label written into metadata.json --
# useful when something other than a human is submitting many canaries and
# wants to tell them apart later (e.g. "canary-for-condition-c-attempt-3").

#SBATCH --job-name=planner-timing-single
#SBATCH --account=research-eemcs-st
#SBATCH --partition=compute-p1
#SBATCH --time=00:10:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem-per-cpu=2G
#SBATCH --output=slurm-logs/planner-timing-single_%j.out
#SBATCH --error=slurm-logs/planner-timing-single_%j.err

module load 2026 cpu
module load python/3.13.12

set -euo pipefail

SCENARIO="$1"
OUT_DIR="$2"
CONDITION="${3:-single}"

cd "$SLURM_SUBMIT_DIR"
mkdir -p slurm-logs

python3 scripts/cold_start_probe/run_planner_direct.py "$SCENARIO" "$OUT_DIR" \
    --condition "$CONDITION" --task-index 0
