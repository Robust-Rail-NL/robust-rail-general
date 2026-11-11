#!/bin/bash
# Submit the Issa-grid pilot on DelftBlue: for each servicing variant (off, on) one chain of dependent
# jobs (generate scenarios -> array of tool runs -> aggregate), all with ONE resource arm for the array.
#
# Run from the repo root of a robust-rail-general checkout on DelftBlue, after
#   module load 2026 cpu; module load python/3.13.18
#   python3 scripts/stage_apptainer_images.py --edge
#
# usage:
#   DRY=1 experiments/issa-grid/submit_pilot.sh ARM          # print the commands only
#   experiments/issa-grid/submit_pilot.sh ARM
# ARM is "daic" (partition daic-eemcs-st, 1 CPU, 16G; runs under ~/linuxhome; set up DAIC first),
#   "p1" (compute-p1, 1 CPU, 3900M: the baseline that ran out of memory in the composition sweep)
#   or "memory" (the memory partition, 1 CPU, 16000M per CPU: shows the real peak).
# Override with PARTITION, CPUS, MEM, TIME if needed. The pilot JSONs issa_pilot_servicing_{off,on}.json are
# read from the directory of this script (override with EXP_DIR); run it from the repo root.
#
# Output: /scratch/$USER/issa_pilot_<arm>_<variant>/ and, after aggregation, ~/issa_pilot_<arm>_<variant>_results/.
# Each output dir gets an arm.txt that says which resources it ran with.
set -euo pipefail

ARM=${1:?usage: submit_pilot.sh p1|memory}
case "$ARM" in
    p1)     : "${PARTITION:=compute-p1}"; : "${CPUS:=1}"; : "${MEM:=3900M}" ;;
    memory) : "${PARTITION:=memory}";     : "${CPUS:=1}"; : "${MEM:=16000M}" ;;
    # DAIC: needs the DAIC site setup first (see pilot-steps.md): SLURM_SITE=daic and `source scripts/slurm/site/daic.env`.
    # /home is 4 MiB there and there is no /scratch, so runs and results live under ~/linuxhome.
    daic)   : "${PARTITION:=daic-eemcs-st}"; : "${CPUS:=1}"; : "${MEM:=16G}"
            : "${SCRATCH_BASE:=$HOME/linuxhome/issa}"; : "${RESULTS_BASE:=$HOME/linuxhome/issa}" ;;
    *) echo "unknown arm: $ARM (p1, memory or daic)" >&2; exit 2 ;;
esac
TIME=${TIME:-00:45:00}
SCRATCH_BASE=${SCRATCH_BASE:-/scratch/$USER}   # where the runs live
RESULTS_BASE=${RESULTS_BASE:-$HOME}             # where aggregated results are copied
EXP_DIR=${EXP_DIR:-$(dirname "$0")}            # where issa_pilot_servicing_*.json are (default: next to this script)

mkdir -p slurm-logs "$SCRATCH_BASE" "$RESULTS_BASE"
run() { if [ "${DRY:-0}" = 1 ]; then echo "[dry] $*" >&2; echo 0; else "$@"; fi; }

for VARIANT in off on; do
    EXP=$EXP_DIR/issa_pilot_servicing_${VARIANT}.json
    OUT=$SCRATCH_BASE/issa_pilot_${ARM}_${VARIANT}
    DEST=$RESULTS_BASE/issa_pilot_${ARM}_${VARIANT}_results
    python3 scripts/slurm_manifest.py "$EXP" --output-dir "$OUT"
    echo "partition=$PARTITION cpus=$CPUS mem_per_cpu=$MEM time=$TIME" > "$OUT/arm.txt"
    ROWS=$(tail -n +2 "$OUT/tasks.tsv" | wc -l)
    LAST=$((ROWS - 1))
    echo "== $VARIANT: $ROWS tasks (array 0-$LAST), $PARTITION, $CPUS cpu, $MEM per cpu, $TIME"

    G=$(run sbatch --parsable scripts/slurm/generate_scenarios.sbatch "$EXP" "$OUT")
    A=$(run sbatch --parsable --dependency=afterok:"$G" --partition="$PARTITION" --cpus-per-task="$CPUS" \
        --mem-per-cpu="$MEM" --time="$TIME" --array="0-$LAST" \
        scripts/slurm/run_experiment_array.sbatch "$OUT/tasks.tsv" "$EXP" "$OUT")
    R=$(run sbatch --parsable --dependency=afterany:"$A" scripts/slurm/aggregate.sbatch "$OUT" "$DEST")
    echo "   generate: $G   array: $A   aggregate: $R"
    [ "${DRY:-0}" = 1 ] || echo "$ARM $VARIANT $A $OUT" >> "$HOME/issa_pilot_jobs.txt"
done
echo "Job ids are appended to ~/issa_pilot_jobs.txt. Report with: ./pilot_report.sh"
