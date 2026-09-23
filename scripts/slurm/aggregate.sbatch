#!/bin/bash
# Aggregation job: run once every scripts/slurm/run_experiment_array.sbatch
# task has finished. Submit with the array job's own ID as a dependency, so
# this never starts early against a still-running sweep:
#
#   sbatch --dependency=afterok:<array_job_id> scripts/slurm/aggregate.sbatch \
#       /scratch/<you>/sweep1 ~/experiments/sweep1
#
# Positional args: $1 output-dir (still on /scratch -- the sweep's working
# location), $2 home-dest (where results get copied to afterward).
#
# Runs report_results.py + coverage_analysis.py over --output-dir exactly as
# run_experiment.py's own sequential path does at the end of a run, then
# copies the whole tree to $2. That copy is not optional: see
# docs/slurm-apptainer.md's storage section -- DelftBlue's /scratch has no
# confirmed purge policy yet, but the login banner itself signals one is
# coming ("The usage of /scratch still needs to be reduced..."), and a
# completed, untouched sweep sitting there is exactly the "inactive data" it
# describes. Nothing here is considered done until it has landed in
# $HOME_DEST -- don't treat /scratch as the final resting place for anything
# from this run.
#
# CERTIFY_THRESHOLD, if set, is passed straight through to report_results.py
# -- there is no --max-duration here to derive one from the way
# run_experiment.py's own _run_report does (this is a separate job from the
# array that ran the actual attempts), so report_results.py's own default
# applies unless you set this explicitly.
#
# TODO: same as run_experiment_array.sbatch -- partition/QOS/walltime/mem
# are placeholders pending the collaborator (see docs/slurm-apptainer.md).
# This job is far lighter than an array task (just report generation + an
# rsync), so its resource needs are smaller, but still unmeasured.

#SBATCH --job-name=robust-rail-experiment-aggregate
#SBATCH --account=research-eemcs-st
#SBATCH --partition=TODO
#SBATCH --time=TODO
#SBATCH --cpus-per-task=1
#SBATCH --mem=TODO
#SBATCH --output=slurm-logs/aggregate_%j.out
#SBATCH --error=slurm-logs/aggregate_%j.err

# Before `set -euo pipefail` -- see run_experiment_array.sbatch's own
# comment on why (Lmod's `module` function vs. set -u) and
# docs/slurm-apptainer.md's "Prerequisites" for the >=3.12 requirement this
# is working around.
module load 2026 cpu
module load python/3.13.12

set -euo pipefail

OUTPUT_DIR="$1"
HOME_DEST="$2"

cd "$(dirname "$0")/../.."  # repo root
mkdir -p slurm-logs

python3 scripts/report_results.py "$OUTPUT_DIR" \
    --runs-csv "$OUTPUT_DIR/runs.csv" \
    --feasibility-csv "$OUTPUT_DIR/feasibility.csv" \
    ${CERTIFY_THRESHOLD:+--certify-threshold "$CERTIFY_THRESHOLD"}

python3 scripts/coverage_analysis.py "$OUTPUT_DIR" \
    --output "$OUTPUT_DIR/coverage_analysis.txt"

mkdir -p "$HOME_DEST"
rsync -a "$OUTPUT_DIR"/ "$HOME_DEST"/
echo "Copied $OUTPUT_DIR -> $HOME_DEST"
