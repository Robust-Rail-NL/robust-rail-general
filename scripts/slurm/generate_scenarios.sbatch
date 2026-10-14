#!/bin/bash
# Generate every instance of an experiment's sweep in parallel, on a compute
# node -- not run_generator.py --experiment --jobs N directly on the shared
# login node. Generation needs no internet (images are already staged in
# ~/apptainer-images via scripts/stage_apptainer_images.py); this exists
# purely to get real accounted CPUs for a --jobs value higher than is
# polite to grab on the login node, rather than any functional need for
# SLURM. The default way to generate scenarios for a sweep -- see
# docs/slurm-apptainer.md's "Running a sweep" step 3.
#
# Submit with: sbatch scripts/slurm/generate_scenarios.sbatch <EXPERIMENT.json> <OUTPUT_DIR>
#
# --cpus-per-task matches the --jobs value below: each generator instance
# looked like a single-core-ish, short-lived process in local testing (see
# run_generator.py's own --jobs, added alongside this script) -- same
# assumption as the planner's own --cpus-per-task=1 in
# run_experiment_array.sbatch. Adjust both together if that turns out wrong
# for a much bigger sweep.

#SBATCH --job-name=generate-scenarios
#SBATCH --account=research-eemcs-st
#SBATCH --partition=compute-p1
#SBATCH --time=00:15:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem-per-cpu=2G
#SBATCH --output=slurm-logs/generate-scenarios_%j.out
#SBATCH --error=slurm-logs/generate-scenarios_%j.err

# Before `set -euo pipefail` -- see run_experiment_array.sbatch's own
# comment on why (Lmod's `module` function vs. set -u).
module load 2026 cpu
module load python/3.13.12

set -euo pipefail

EXPERIMENT="$1"
OUTPUT_DIR="$2"

# Must be submitted from the repo root -- $SLURM_SUBMIT_DIR is that
# directory, reliably, unlike deriving it from this script's own path (see
# run_experiment_array.sbatch's own note on why).
cd "$SLURM_SUBMIT_DIR"
mkdir -p slurm-logs

# The experiment file's own generator version, not a hardcoded guess --
# matches scripts/slurm_manifest.py's own printed suggestion.
GENERATOR_VERSION=$(python3 -c "
import sys; sys.path.insert(0, '.')
from scripts import experiment_spec
print(experiment_spec.load('$EXPERIMENT')['versions']['generator'])
")

python3 run_generator.py --experiment "$EXPERIMENT" --run-dir "$OUTPUT_DIR" \
    --version "$GENERATOR_VERSION" --engine apptainer --jobs 8
