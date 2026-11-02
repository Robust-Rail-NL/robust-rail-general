#!/bin/bash
# Conditions (b)/(c)/(d): ~25 simultaneous planner runs against the same
# scenario, one MODE covering all three so they stay in sync with each
# other (same mounts, same scenario, same resource request):
#
#   shared   condition (b): every task reads the .sif straight from the
#            shared staging cache (~/apptainer-images), same as a real
#            sweep -- the baseline this whole probe is trying to explain.
#   local    condition (c): every task first copies the .sif to its own
#            node-local storage ($TMPDIR) and runs from that copy instead.
#            If this removes the slowdown, that is also the fix to apply
#            to real sweeps.
#   warmup   condition (d): every task runs once first (discarded output)
#            before its real timed run, self-warming that task's own node
#            right before the measurement. Adapted from "one dummy run per
#            node first" -- which physical node a task lands on isn't known
#            before SLURM dispatches it, so pre-warming specific nodes ahead
#            of time isn't mechanically possible; warming each task's own
#            node immediately before its own timed run is the closest
#            equivalent achievable without that information.
#
# All 25 tasks are submitted together as one array and read the identical
# scenario file -- SLURM doesn't guarantee literally simultaneous dispatch,
# so this doesn't force synchronized starts. Don't assume it: each task's
# own start_time lands in its metadata.json, and
# scripts/cold_start_probe/summarize_planner_timing.py reports the actual
# observed spread (max start_time - min start_time) across the condition's
# 25 tasks as part of its summary, rather than asserting synchrony that
# wasn't verified.
#
# Submit from the repo root with:
#   sbatch --array=0-24 scripts/cold_start_probe/planner-timing-array.sbatch \
#       <MODE> <SCENARIO.json> <OUT_BASE>
# where MODE is shared/local/warmup and OUT_BASE gets one task_<N>/
# subdirectory per array task.

#SBATCH --job-name=planner-timing-array
#SBATCH --account=research-eemcs-st
#SBATCH --partition=compute-p1
#SBATCH --time=00:10:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
# --mem=0 means "all memory on the node" -- required by this cluster
# whenever --exclusive is set; a --mem-per-cpu value here instead makes
# sbatch reject the submission outright ("This job submission doesn't
# specify the amount of memory per-node... specify '--mem=0'"), found
# 2026-10-26 on the first real resume attempt after adding --exclusive.
#SBATCH --mem=0
# --exclusive: without this, SLURM is free to pack many single-cpu tasks
# from this same array onto one node, since each only asks for 1 cpu --
# found 2026-10-18 when a real 25-task array landed on only 3 distinct
# nodes (16/2/7 tasks respectively), conflating "per-node first use" (later
# tasks on the same node ran fast, reusing the first task's now-warm
# node-local cache) with node-level CPU contention (one node's 7 tasks were
# all uniformly slow regardless of order, suggesting concurrent-task
# contention, not cache state) -- exactly the two effects this experiment
# needs to tell apart. --exclusive reserves the whole node per task, so
# "node" in the recorded metadata genuinely means one task, one node, every
# time. Costs more: this asks for up to 25 whole free nodes at once instead
# of 25 free cores, a much scarcer resource on a partition that runs mostly
# full -- expect these array submissions to queue longer than before.
#SBATCH --exclusive
#SBATCH --output=slurm-logs/planner-timing-array_%A_%a.out
#SBATCH --error=slurm-logs/planner-timing-array_%A_%a.err

module load 2026 cpu
module load python/3.13.12

set -euo pipefail

MODE="$1"
SCENARIO="$2"
OUT_BASE="$3"

cd "$SLURM_SUBMIT_DIR"
mkdir -p slurm-logs

OUT_DIR="$OUT_BASE/task_${SLURM_ARRAY_TASK_ID}"

case "$MODE" in
    shared)
        EXTRA_ARGS=()
        ;;
    local)
        # $TMPDIR is node-local on DelftBlue compute nodes (cleaned up when
        # the job ends) -- if it's unset for some reason, fall back to a
        # per-task directory under /tmp instead of silently using shared
        # storage, which would defeat the whole point of this condition.
        LOCAL_DIR="${TMPDIR:-/tmp/planner-timing-$SLURM_JOB_ID-$SLURM_ARRAY_TASK_ID}"
        mkdir -p "$LOCAL_DIR"
        EXTRA_ARGS=(--copy-sif-to "$LOCAL_DIR")
        ;;
    warmup)
        EXTRA_ARGS=(--warmup)
        ;;
    *)
        echo "Unknown MODE '$MODE' -- expected shared, local or warmup." >&2
        exit 1
        ;;
esac

python3 scripts/cold_start_probe/run_planner_direct.py "$SCENARIO" "$OUT_DIR" \
    --condition "$MODE" --task-index "$SLURM_ARRAY_TASK_ID" "${EXTRA_ARGS[@]}"
