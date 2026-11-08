# Provenance of the Issa grid results (draft; fill in the DAIC-only items)

Drafted 2026-11-08. Items marked TODO can only be read on DAIC.

## What ran

| Component | Build string (first line of the tool's output) | Full commit | Image digest (DAIC `.sif.digest`) |
|---|---|---|---|
| solver (HIP), image `ghcr.io/robust-rail-nl/hip:edge` | `HIP 2.2.0-edge+20261106.965fd71` | `965fd7192a7e35bfede7635ae6ede1ce84460e7b` (robust-rail-solver, branch `edge`, a "Merge branch 'main' into edge" that includes PR #79, the fix for #75) | TODO |
| planner, image `ghcr.io/robust-rail-nl/planner:edge` | `robust-rail-planner 0.5.0-edge+20261106.2f2f34b` | `2f2f34b0157a4846762ced82fc925b5218b3fb0f` (robust-rail-planner, branch `edge`, includes PR #60 timing/stats lines and #59) | TODO |
| generator, image `ghcr.io/robust-rail-nl/generator:latest` | v2.5.0 | `a3271fd0df499353d3234371e5444031b578366f` (tag `v2.5.0`) | TODO; the exact image id of each generation is also in every `scenario_<instance>.generator.json` (`generator_image_id`) |
| evaluator (TORS), image `ghcr.io/robust-rail-nl/tors:edge` | TODO: `head -1 <instance>/local_search/eval.out` on DAIC (a local run printed `TORS 2.3.0-edge+20261103.50bc79e`, which need not be the cluster's) | TODO | TODO |
| experiment tooling | robust-rail-general `main` at `8fea78e55a867c515bd6bf4966622e459987bd45` plus branch `daic-port` merged locally on DAIC | | |

## Runs behind `results/first_grid.csv`

SLURM array ids on DAIC (task index = row of `tasks.tsv`, largest scenarios first): servicing off, 1 to 6 trains: 110812 (solver), 110813 (enhsp), 110814 (symbolic-rail); servicing on, 2 to 6 trains: 110986, 110987, 110988; servicing off, 7 to 10 trains: 112992, 112993, 112994; servicing on, 7 to 10 trains: 113037, 113038, 113039. The first servicing-on submission (110818 to 110820) was cancelled by the scheduler because its generate job exited 1 (1 train with servicing cannot be generated). Their accounting is in `results/sacct_first_grid.txt`.

## Experiment definitions

`issa_grid_servicing_{off,on}.json` (seed 700, trains 1 to 10, 3 matchings, 5 instances, `max_duration` 1800, `reject_infeasible` true) and, for the extension, `issa_grid_ext_servicing_{off,on}.json` (`number_of_instances` 15, instances 5 to 14 run, trains 3 to 8, enhsp trains 3 and 4 only). The scenarios of instances 0 to 4 are identical in both because the generator seeds an instance as `seed*(j+i+1)`.

Hardware: DAIC partition `daic-eemcs-st`, nodes `gpu47`, `gpu49`, `gpu51`, `gpu52` (per-run node in the CSV column `node`), 1 CPU per task, memory per task 4G (solver), 32G (enhsp), 12G (symbolic-rail), 45 min limit, 1800 s tool budget.

Servicing on has no 1-train cell: the generator refuses it (time window 1440, servicing time 300, `min_gap_on_gateway` 480).

## How to fill in the TODO items on DAIC

```bash
source scripts/slurm/site/daic.env
for f in "$SIF_CACHE_DIR"/*.digest; do echo "$(basename "$f" .sif.digest)  $(cat "$f")"; done
head -qn1 ~/linuxhome/issa/issa_grid_off/custom_2_FIFO_0/local_search/eval.out
grep -h '"generator_image_id"' ~/linuxhome/issa/issa_grid_{off,on}/*/scenario_*.generator.json | sort | uniq -c
```
