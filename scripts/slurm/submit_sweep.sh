#!/bin/bash
# Submit a whole sweep as a chain of dependent SLURM jobs, so nothing depends on this login session.
#
# usage (from the repo root):
#   DRY=1 scripts/slurm/submit_sweep.sh EXPERIMENT.json OUTPUT_DIR HOME_DEST [TIME] [THROTTLE]
#   scripts/slurm/submit_sweep.sh EXPERIMENT.json OUTPUT_DIR HOME_DEST [TIME] [THROTTLE]
#   SLURM_SITE=daic scripts/slurm/submit_sweep.sh ...     # the same, on DAIC
#
#   TIME        per-task limit, default 00:45:00 (the sbatch script's own default is 8 minutes)
#   THROTTLE    most array tasks running at once, default 40
#   DRY=1       only print the commands
#   SLURM_SITE  which scripts/slurm/site/<name>.env to use: account, partition, python module and
#               cache directories. Default delftblue. The environment is passed on to the jobs.
#
# Stages: manifest (runs here, cheap) -> generate scenarios -> array of tasks -> aggregate.
# The array starts only if generation succeeded (afterok). The aggregation starts when the array has
# ended, whether or not every task succeeded (afterany).

# Before `set -euo pipefail`: Lmod's `module` function can trip `set -u`.
export SLURM_SITE="${SLURM_SITE:-delftblue}"
SITE_FILE="scripts/slurm/site/$SLURM_SITE.env"
if [ ! -f "$SITE_FILE" ]; then
    echo "ERROR: no $SITE_FILE (run from the repo root; known sites: $(ls scripts/slurm/site | sed 's/\.env$//' | tr '\n' ' '))" >&2
    exit 1
fi
source "$SITE_FILE"
if command -v module >/dev/null 2>&1; then
    module load 2026 cpu
    module load "$PYTHON_MODULE"
fi

set -euo pipefail

EXP=$1; OUT=$2; DEST=$3; TIME=${4:-00:45:00}; THROTTLE=${5:-40}

mkdir -p slurm-logs
python3 scripts/slurm_manifest.py "$EXP" --output-dir "$OUT"

# tasks.tsv has a header row; array indices run from 0 to (rows - 1).
ROWS=$(tail -n +2 "$OUT/tasks.tsv" | wc -l)
LAST=$((ROWS - 1))
echo "site: $SLURM_SITE (account $SBATCH_ACCOUNT, partition $SBATCH_PARTITION)"
echo "tasks: $ROWS (array 0-$LAST%$THROTTLE), time per task: $TIME"

run() {
    if [ "${DRY:-0}" = 1 ]; then echo "[dry] $*" >&2; echo 0; else "$@"; fi
}

G=$(run sbatch --parsable scripts/slurm/generate_scenarios.sbatch "$EXP" "$OUT")
A=$(run sbatch --parsable --dependency=afterok:"$G" --time="$TIME" --array="0-$LAST%$THROTTLE" \
    scripts/slurm/run_experiment_array.sbatch "$OUT/tasks.tsv" "$EXP" "$OUT")
R=$(run sbatch --parsable --dependency=afterany:"$A" scripts/slurm/aggregate.sbatch "$OUT" "$DEST")

echo "generate: $G   array: $A   aggregate: $R"
echo "watch with: squeue -u \$USER ; results end up in $DEST"
