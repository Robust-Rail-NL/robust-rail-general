#!/bin/bash
# SLURM array job: one task per (instance, tool[, seed]) attempt from a
# scripts/slurm_manifest.py manifest. Generate the manifest first, then
# submit with the exact command it prints, e.g.:
#
#   sbatch --array=0-41 scripts/slurm/run_experiment_array.sbatch \
#       /scratch/<you>/sweep1/tasks.tsv KleineBinckhorst /scratch/<you>/sweep1
#
# Positional args: $1 manifest, $2 location, $3 output-dir. Assumes it's
# submitted from the repo root (the `cd` below is relative to this script's
# own location, so it doesn't actually matter where `sbatch` is invoked
# from, but the #SBATCH --output/--error paths below are still resolved
# against the submission directory by SLURM itself).
#
# Version/max-duration are read from env vars if set -- export them before
# `sbatch`, or pass `--export=SOLVER_VERSION=...,...` -- rather than being
# separate positional args, so this file doesn't need editing per sweep.
#
# --sif-cache-dir is not overridable here: scripts/stage_apptainer_images.py
# and scripts/slurm_run_task.py share the same default
# (docker_utils.DEFAULT_SIF_CACHE_DIR, ~/apptainer-images) -- override
# SIF_CACHE_DIR below only if you staged somewhere else.
#
# TODO before this is actually runnable: partition/QOS and walltime/mem/cpu
# below are placeholders -- still pending input from the collaborator who
# runs this (see __scratch/slurm-apptainer-status.md). --account is filled
# in (Léon's own value).

#SBATCH --job-name=robust-rail-experiment
#SBATCH --account=research-eemcs-st
#SBATCH --partition=TODO
# Comfortably above --max-duration (the solver's own graceful-stop budget,
# plus its BACKSTOP_GRACE) and run_planner.py's DEFAULT_PLANNER_TIMEOUT
# (600s) for the slowest instance in the sweep -- a real number from the
# collaborator, not a measured one.
#SBATCH --time=TODO
#SBATCH --cpus-per-task=TODO
#SBATCH --mem=TODO
#SBATCH --output=slurm-logs/%A_%a.out
#SBATCH --error=slurm-logs/%A_%a.err

set -euo pipefail

MANIFEST="$1"
LOCATION="$2"
OUTPUT_DIR="$3"

cd "$(dirname "$0")/../.."  # repo root
mkdir -p slurm-logs

python3 scripts/slurm_run_task.py \
    --manifest "$MANIFEST" \
    --location "$LOCATION" \
    --output-dir "$OUTPUT_DIR" \
    --solver-version "${SOLVER_VERSION:-stable}" \
    --planner-version "${PLANNER_VERSION:-stable}" \
    --evaluator-version "${EVALUATOR_VERSION:-stable}" \
    ${MAX_DURATION:+--max-duration "$MAX_DURATION"} \
    ${SIF_CACHE_DIR:+--sif-cache-dir "$SIF_CACHE_DIR"}
