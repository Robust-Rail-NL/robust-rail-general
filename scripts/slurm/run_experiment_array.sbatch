#!/bin/bash
# SLURM array job: one task per (instance, tool[, seed]) attempt from a
# scripts/slurm_manifest.py manifest. Generate the manifest first, then
# submit with the exact command it prints, e.g.:
#
#   sbatch --array=0-41 scripts/slurm/run_experiment_array.sbatch \
#       /scratch/<you>/sweep1/tasks.tsv experiments/sweep1.json /scratch/<you>/sweep1
#
# Positional args: $1 manifest, $2 experiment JSON, $3 output-dir. Assumes it's
# submitted from the repo root (the `cd` below is relative to this script's
# own location, so it doesn't actually matter where `sbatch` is invoked
# from, but the #SBATCH --output/--error paths below are still resolved
# against the submission directory by SLURM itself).
#
# Versions, max-duration and the rest come from the experiment JSON itself
# (see scripts/experiment_spec.py), the same file run_experiment.py reads.
#
# --sif-cache-dir is not overridable here: scripts/stage_apptainer_images.py
# and scripts/slurm_run_task.py share the same default
# (docker_utils.DEFAULT_SIF_CACHE_DIR, ~/apptainer-images) -- override
# SIF_CACHE_DIR below only if you staged somewhere else.
#
# --account/--partition/--ntasks are filled in (Léon's own value; compute-p1
# proven repeatedly; --ntasks=1 and --mem-per-cpu, not --mem, are DelftBlue
# sbatch requirements -- a bare --mem or an omitted --ntasks are refused
# outright at submission, found 2026-10-14).
#
# --cpus-per-task/--mem-per-cpu/--time below come from a single real
# measurement (2026-10-14, /usr/bin/time -v over scripts/slurm_run_task.py,
# one planner attempt, 5 trains, max_duration 300, via __scratch/
# cluster-smoke-test-planner.json): 72.37s elapsed, 83% of one core, 452568
# KB peak RSS. That run didn't time out (evaluator rejected the plan at
# 68.9s, well under budget), so it bounds typical-case cost, not the
# worst case -- a full 300s timeout's own memory/cpu footprint hasn't been
# measured, nor has the solver's (only separately confirmed to run
# successfully, not profiled the same way). Treat these as a reasoned
# starting point to actually get the array submitted, not a final answer --
# revisit if OOM-kills or walltime-kills show up for real in the sweep.

#SBATCH --job-name=robust-rail-experiment
#SBATCH --account=research-eemcs-st
#SBATCH --partition=compute-p1
# 300s max_duration + ~180s margin (evaluator + Julia/dotnet startup +
# teardown + scheduler slack) -- comfortably above both the solver's own
# worst case (max_duration + BACKSTOP_GRACE = 420s) and the one measured
# planner attempt (72s, nowhere near this limit).
#SBATCH --time=00:08:00
#SBATCH --ntasks=1
# The one measured planner attempt stayed under 100% of a single core (83%);
# no evidence either tool needs more than one.
#SBATCH --cpus-per-task=1
# ~4.5x the one measured peak RSS (442MB) for GC/evaluator/OS headroom --
# still far below the untested 3900M guess used for tonight's sizing run.
#SBATCH --mem-per-cpu=2G
#SBATCH --output=slurm-logs/%A_%a.out
#SBATCH --error=slurm-logs/%A_%a.err

# Before `set -euo pipefail`, deliberately: Lmod's `module` shell function
# can itself trip `set -u` (references variables that may be unset), and a
# compute node's default python3 doesn't meet pyproject.toml's >=3.12 (see
# docs/slurm-apptainer.md's "Prerequisites"). Confirmed correct on a real
# compute node via sbatch, not just the login node, 2026-10-14. apptainer
# itself needed no module load on the login node, so nothing is loaded for
# it here -- if a compute node turns out to differ, add it here too.
module load 2026 cpu
module load python/3.13.12

set -euo pipefail

MANIFEST="$1"
EXPERIMENT="$2"
OUTPUT_DIR="$3"

cd "$(dirname "$0")/../.."  # repo root
mkdir -p slurm-logs

python3 scripts/slurm_run_task.py \
    --manifest "$MANIFEST" \
    --experiment "$EXPERIMENT" \
    --output-dir "$OUTPUT_DIR" \
    ${SIF_CACHE_DIR:+--sif-cache-dir "$SIF_CACHE_DIR"}
