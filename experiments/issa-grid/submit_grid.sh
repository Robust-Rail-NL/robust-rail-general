#!/bin/bash
# Submit one servicing variant of the Issa grid on DelftBlue as a chain of dependent jobs:
#   manifest (here) -> generate scenarios -> one array per tool class -> aggregate.
# Tool classes: solver, enhsp, symbolic-rail. Each class gets its own array so it can have its own
# partition and memory; the manifest's tool/planner columns decide which task index belongs to which class.
#
# Run from the repo root of a robust-rail-general checkout on DelftBlue (with main containing the
# reject_infeasible key), after
#   module load 2026 cpu; module load python/3.13.18
#   python3 scripts/stage_apptainer_images.py --edge
#
# usage:
#   DRY=1 experiments/issa-grid/submit_grid.sh EXPERIMENT.json OUTPUT_DIR HOME_DEST      # print the commands only
#   experiments/issa-grid/submit_grid.sh EXPERIMENT.json OUTPUT_DIR HOME_DEST
# e.g. experiments/issa-grid/submit_grid.sh experiments/issa-grid/issa_grid_servicing_off.json /scratch/$USER/issa_grid_off ~/issa_grid_off_results
# (always from the repo root: it calls scripts/slurm_manifest.py and scripts/slurm/*.sbatch by relative path)
#
# Per-class resources (defaults are the compute-p1 baseline; set from the pilot results):
#   SOLVER_PARTITION  SOLVER_MEM  SOLVER_CPUS  SOLVER_THROTTLE
#   ENHSP_PARTITION   ENHSP_MEM   ENHSP_CPUS   ENHSP_THROTTLE
#   SYMBOLIC_PARTITION SYMBOLIC_MEM SYMBOLIC_CPUS SYMBOLIC_THROTTLE
#   GENERATE_CPUS (optional, default the script's 8)   TIME (per task, default 00:45:00)      HARDEST_FIRST=1 (default) runs the largest scenarios first
# On DAIC: export SLURM_SITE=daic; source scripts/slurm/site/daic.env first; the defaults then are daic-eemcs-st with 4G / 12G / 32G for solver / symbolic-rail / enhsp.
# Example (symbolic-rail on the memory partition, DelftBlue):
#   SYMBOLIC_PARTITION=memory SYMBOLIC_MEM=16000M experiments/issa-grid/submit_grid.sh ...
# The three throttles default to 20 each (60 running tasks at most; the account allows 64 jobs).
#
# Staging by train count: the experiment JSON always describes the whole grid (one scenario set, one output dir). TRAINS_MIN and
# TRAINS_MAX (inclusive) pick which tasks to submit; e.g. TRAINS_MAX=6 first, then later, on the same OUTPUT_DIR,
#   TRAINS_MIN=7 SKIP_GENERATE=1 experiments/issa-grid/submit_grid.sh ...      (scenarios already exist; no generate job, no dependency)
# Do NOT split the experiment into two JSON files: the generator seeds each instance as seed*(j+i+1) with j the position in
# number_of_trains, so a second file would generate different scenarios than the full grid. Task indices are deterministic
# for a given experiment, so both stages use the same tasks.tsv numbering (the extraction takes the array ids of both).
#
# More instances (an extension on its OWN output directory, so the numbering of tasks.tsv of the first run stays valid):
# INSTANCE_MIN / INSTANCE_MAX pick instance numbers (the <i> of custom_<trains>_<matching>_<i>); SOLVER_TRAINS_MAX,
# ENHSP_TRAINS_MAX and SYMBOLIC_TRAINS_MAX cap the train count per tool (default: TRAINS_MAX). Instances 0..4 of an
# extended experiment (number_of_instances 15, same trains list) are identical to the first run's, because the
# generator's seed is seed*(j+i+1); they are simply not submitted with INSTANCE_MIN=5.
#
# PRUNE_MANIFEST=1 (for an extension on a fresh output dir): tasks.tsv keeps only the selected tasks, renumbered 0..N-1, so array
# indices stay below SLURM's MaxArraySize (check: scontrol show config | grep MaxArraySize; the default is 1001).
#
# After the arrays end the aggregation job runs whether or not every task succeeded (afterany).
# GEN_DEP=afterany makes the arrays start even if the generate job exits 1 (some scenarios cannot be generated, for example
# 1 train with servicing in a 1440 window; their tasks then fail fast and show as no_scenario). Default afterok.
# GENERATE_TIME overrides the generate job's 15 min limit (450 scenarios take longer than 150).
# Job ids and the resources used are written to OUTPUT_DIR/grid_jobs.txt and appended to ~/issa_grid_jobs.txt.
set -euo pipefail

EXP=${1:?usage: submit_grid.sh EXPERIMENT.json OUTPUT_DIR HOME_DEST}
OUT=${2:?missing OUTPUT_DIR}
DEST=${3:?missing HOME_DEST}

TIME=${TIME:-00:45:00}
# Site defaults. DAIC (SLURM_SITE=daic; also `source scripts/slurm/site/daic.env` first): partition daic-eemcs-st and, per
# tool, the memory the DAIC pilot suggests at 10 trains after 30 min (MaxRSS: solver 0.6-0.9 GB, symbolic-rail 5.4-5.8 GB,
# enhsp 10.8 and 16.8 GB, the latter at the 16G limit): solver 4G, symbolic-rail 12G, enhsp 32G. DelftBlue (default):
# compute-p1 and 3900M for every tool, which the pilot says is too little for either planner at 10 trains; put the
# planners on the memory partition there (PARTITION=memory, MEM=16000M).
if [ "${SLURM_SITE:-delftblue}" = daic ]; then
    DEF_PART=daic-eemcs-st; DEF_SOLVER_MEM=4G; DEF_SYMBOLIC_MEM=12G; DEF_ENHSP_MEM=32G
else
    DEF_PART=compute-p1; DEF_SOLVER_MEM=3900M; DEF_SYMBOLIC_MEM=3900M; DEF_ENHSP_MEM=3900M
fi
: "${SOLVER_PARTITION:=$DEF_PART}";   : "${SOLVER_MEM:=$DEF_SOLVER_MEM}";     : "${SOLVER_CPUS:=1}";   : "${SOLVER_THROTTLE:=20}"
: "${ENHSP_PARTITION:=$DEF_PART}";    : "${ENHSP_MEM:=$DEF_ENHSP_MEM}";       : "${ENHSP_CPUS:=1}";    : "${ENHSP_THROTTLE:=20}"
: "${SYMBOLIC_PARTITION:=$DEF_PART}"; : "${SYMBOLIC_MEM:=$DEF_SYMBOLIC_MEM}"; : "${SYMBOLIC_CPUS:=1}"; : "${SYMBOLIC_THROTTLE:=20}"
GEN_ARGS="${GENERATE_CPUS:+--cpus-per-task=$GENERATE_CPUS} ${GENERATE_TIME:+--time=$GENERATE_TIME}"   # optional: fewer than the script's 8 CPUs if nodes are busy

mkdir -p slurm-logs
TASKS=$OUT/tasks.tsv
# A later stage on the same OUTPUT_DIR (SKIP_GENERATE=1) must reuse tasks.tsv as it is: rebuilding it rewrites the file in the
# manifest's own order for a moment before it is renumbered, and an array task that starts in that window would read the
# wrong row. Arrays of an earlier stage may still be running.
REUSE_TASKS=0
if [ "${SKIP_GENERATE:-0}" = 1 ] && [ -s "$TASKS" ]; then
    REUSE_TASKS=1
    echo "reusing existing $TASKS (not rebuilding it)"
else
    python3 scripts/slurm_manifest.py "$EXP" --output-dir "$OUT" > /dev/null
fi

# Optionally renumber the tasks so the largest scenarios get the lowest indices: SLURM starts array tasks
# roughly in index order, and the 10-train runs are the long ones, so starting them first avoids a long tail.
# The index column has no meaning beyond lookup (slurm_run_task.py --index N finds the row with index N).
if { [ "${HARDEST_FIRST:-1}" = 1 ] || [ "${PRUNE_MANIFEST:-0}" = 1 ]; } && [ "$REUSE_TASKS" = 0 ]; then
    CAP_DEFAULT=${TRAINS_MAX:-999}
    PRUNE=${PRUNE_MANIFEST:-0} HARDEST=${HARDEST_FIRST:-1} TMIN=${TRAINS_MIN:-0} IMIN=${INSTANCE_MIN:-0} IMAX=${INSTANCE_MAX:-999999} \
    CAP_SOLVER=${SOLVER_TRAINS_MAX:-$CAP_DEFAULT} CAP_ENHSP=${ENHSP_TRAINS_MAX:-$CAP_DEFAULT} CAP_SYMBOLIC=${SYMBOLIC_TRAINS_MAX:-$CAP_DEFAULT} \
    python3 - "$TASKS" <<'PY'
import csv, os, re, sys
path = sys.argv[1]
with open(path, newline="") as f:
    reader = csv.DictReader(f, delimiter="\t")
    rows, fields = list(reader), reader.fieldnames
if rows and not all(row["index"] == str(i) for i, row in enumerate(rows)):
    sys.exit("tasks.tsv indices are not 0..N-1 in file order; refusing to renumber")
trains = lambda r: int(re.match(r"custom_(\d+)_", r["instance"]).group(1))
inst = lambda r: int(re.match(r"custom_\d+_[A-Za-z]+_(\d+)$", r["instance"]).group(1))
if os.environ["PRUNE"] == "1":
    # Keep only the selected tasks and number them 0..N-1: SLURM refuses array indices above MaxArraySize (default 1001),
    # which a 1350-task manifest with a selection in the middle exceeds. The extraction then sees only the selected tasks.
    cap = {"solver": os.environ["CAP_SOLVER"], "enhsp": os.environ["CAP_ENHSP"], "symbolic-rail": os.environ["CAP_SYMBOLIC"]}
    klass = lambda r: "solver" if r["tool"] == "solver" else r["planner"]
    rows = [r for r in rows if int(os.environ["TMIN"]) <= trains(r) <= int(cap[klass(r)])
            and int(os.environ["IMIN"]) <= inst(r) <= int(os.environ["IMAX"])]
if os.environ["HARDEST"] == "1":
    rows.sort(key=lambda r: -trains(r))   # stable: ties keep the manifest's order
for i, row in enumerate(rows):
    row["index"] = str(i)
with open(path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fields, delimiter="\t")
    writer.writeheader()
    writer.writerows(rows)
PY
fi

# Index list per class, as SLURM array syntax (e.g. 0-2,5,7-9).
index_list() {
    python3 - "$TASKS" "$1" "${TRAINS_MIN:-0}" "$2" "${INSTANCE_MIN:-0}" "${INSTANCE_MAX:-999999}" <<'PY'
import csv, re, sys
path, cls, tmin, tmax = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
imin, imax = int(sys.argv[5]), int(sys.argv[6])
with open(path, newline="") as f:
    rows = list(csv.DictReader(f, delimiter="\t"))
def klass(r):
    return "solver" if r["tool"] == "solver" else r["planner"]
def trains(r):
    return int(re.match(r"custom_(\d+)_", r["instance"]).group(1))
def inst(r):
    return int(re.match(r"custom_\d+_[A-Za-z]+_(\d+)$", r["instance"]).group(1))
idx = sorted(int(r["index"]) for r in rows if klass(r) == cls and tmin <= trains(r) <= tmax and imin <= inst(r) <= imax)
out, start = [], None
for i, v in enumerate(idx):
    if start is None:
        start = prev = v
    elif v == prev + 1:
        prev = v
    else:
        out.append(f"{start}-{prev}" if prev > start else str(start)); start = prev = v
    if i == len(idx) - 1:
        out.append(f"{start}-{prev}" if prev > start else str(start))
print(",".join(out))
PY
}

run() { if [ "${DRY:-0}" = 1 ]; then echo "[dry] $*" >&2; echo 0; else "$@"; fi; }

# Refuse a partition this cluster does not have (typically SLURM_SITE not exported in this shell: the default is delftblue).
if command -v sinfo >/dev/null 2>&1; then
    for p in "$SOLVER_PARTITION" "$ENHSP_PARTITION" "$SYMBOLIC_PARTITION"; do
        if [ -z "$(sinfo -h -p "$p" 2>/dev/null)" ]; then
            echo "ERROR: no partition '$p' on this cluster. On DAIC: export SLURM_SITE=daic; source scripts/slurm/site/daic.env" >&2
            exit 1
        fi
    done
fi
echo "site: ${SLURM_SITE:-delftblue}"
echo "tasks: $(($(wc -l < "$TASKS") - 1)) in $TASKS, time per task $TIME"
if [ "${SKIP_GENERATE:-0}" = 1 ]; then
    G=""   # scenarios already generated by an earlier stage on this OUTPUT_DIR
    DEP=""
else
    G=$(run sbatch --parsable $GEN_ARGS scripts/slurm/generate_scenarios.sbatch "$EXP" "$OUT")
    DEP="--dependency=${GEN_DEP:-afterok}:$G"
fi

ARRAYS=""
echo "# $(date +%F\ %T) site=${SLURM_SITE:-delftblue} trains=${TRAINS_MIN:-0}-${TRAINS_MAX:-999} generate=${G:-skipped}" >> "$OUT/grid_jobs.txt"
submit_class() {  # class partition mem cpus throttle
    local cls=$1 part=$2 mem=$3 cpus=$4 thr=$5 cap=$6 list job
    list=$(index_list "$cls" "$cap")
    if [ -z "$list" ]; then echo "   no $cls tasks"; return; fi
    echo "== $cls: indices $list on $part, $cpus cpu, $mem per cpu, throttle $thr"
    job=$(run sbatch --parsable $DEP --job-name="issa-$cls" --partition="$part" \
        --cpus-per-task="$cpus" --mem-per-cpu="$mem" --time="$TIME" --array="$list%$thr" \
        scripts/slurm/run_experiment_array.sbatch "$TASKS" "$EXP" "$OUT")
    ARRAYS="${ARRAYS:+$ARRAYS:}$job"
    echo "$cls $job partition=$part cpus=$cpus mem_per_cpu=$mem time=$TIME" >> "$OUT/grid_jobs.txt"
    [ "${DRY:-0}" = 1 ] || echo "$cls $job $OUT" >> "$HOME/issa_grid_jobs.txt"
}
submit_class solver        "$SOLVER_PARTITION"   "$SOLVER_MEM"   "$SOLVER_CPUS"   "$SOLVER_THROTTLE" "${SOLVER_TRAINS_MAX:-${TRAINS_MAX:-999}}"
submit_class enhsp         "$ENHSP_PARTITION"    "$ENHSP_MEM"    "$ENHSP_CPUS"    "$ENHSP_THROTTLE" "${ENHSP_TRAINS_MAX:-${TRAINS_MAX:-999}}"
submit_class symbolic-rail "$SYMBOLIC_PARTITION" "$SYMBOLIC_MEM" "$SYMBOLIC_CPUS" "$SYMBOLIC_THROTTLE" "${SYMBOLIC_TRAINS_MAX:-${TRAINS_MAX:-999}}"

R=$(run sbatch --parsable --dependency=afterany:"$ARRAYS" scripts/slurm/aggregate.sbatch "$OUT" "$DEST")
echo "aggregate $R" >> "$OUT/grid_jobs.txt"
echo "generate: ${G:-skipped}   arrays: $ARRAYS   aggregate: $R"
echo "watch with: squeue -u \$USER ; results end up in $DEST ; job table: $OUT/grid_jobs.txt"
