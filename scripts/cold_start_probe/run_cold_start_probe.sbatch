#!/bin/bash
# Runs the cold-start probe orchestrator itself as a SLURM job, not a
# login-node background process. A login-node-launched orchestrator
# (setsid+nohup+disown) was twice found to have gone silent or to have
# produced results mixed with a second, untraceable instance (2026-10-18)
# -- DelftBlue has 4 login nodes, and the leading theory is a background
# process surviving on a login node other than the one currently being
# watched, not any single session time limit (an earlier theory blaming
# systemd-logind session accounting was never confirmed, and a 4-login-node
# `pgrep` swept for the process found nothing, weakening it further). A
# SLURM job sidesteps the question entirely either way: it has its own,
# explicit, SLURM-accounted --time budget, tied to a job ID `squeue`/`sacct`
# can always find regardless of which node launched it.
#
# Submit from the repo root with:
#   sbatch scripts/cold_start_probe/run_cold_start_probe.sbatch <SCENARIO.json> <OUT_BASE> [extra args...]
# (any extra args are forwarded as-is to run_cold_start_probe.py, e.g.
# --canary-retry-backoff 1.0 to disable backoff)
#
# This job submits further sbatch jobs of its own (the single/array probe
# tasks) from inside itself -- true on most clusters that sbatch/squeue
# remain callable from a running job, same as from the login node, but
# worth a quick manual check if this refuses to work: srun --pty bash onto
# a compute node and try `squeue -u $USER` by hand first.
#
# --time=3-00:00:00: generous relative to run_cold_start_probe.py's own
# --max-wait-hours default (48h *per condition*, not total) -- in the
# extremely unlikely worst case where every one of the 4 conditions needs
# its full 48h ceiling this still wouldn't be enough, but that would also
# mean something is badly wrong worth noticing and intervening on manually,
# not something to blindly provision for. compute-p1's own partition limit
# is 5 days, so there's room to raise this if needed.

#SBATCH --job-name=cold-start-probe-orchestrator
#SBATCH --account=research-eemcs-st
#SBATCH --partition=compute-p1
#SBATCH --time=3-00:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem-per-cpu=1G
#SBATCH --output=slurm-logs/cold-start-probe-orchestrator_%j.out
#SBATCH --error=slurm-logs/cold-start-probe-orchestrator_%j.err

# Before `set -euo pipefail` -- see scripts/slurm/run_experiment_array.sbatch's
# own comment on why (Lmod's `module` function vs. set -u).
module load 2026 cpu
module load python/3.13.12

set -euo pipefail

# Must be submitted from the repo root -- $SLURM_SUBMIT_DIR is that
# directory, reliably, unlike deriving it from this script's own path (see
# scripts/slurm/run_experiment_array.sbatch's own note on why).
cd "$SLURM_SUBMIT_DIR"
mkdir -p slurm-logs

python3 scripts/cold_start_probe/run_cold_start_probe.py "$@"
