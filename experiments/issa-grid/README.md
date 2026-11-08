# Issa grid: solver vs ENHSP vs symbolic-rail

A comparison of the HIP solver, the ENHSP planner and the symbolic-rail planner (SymbolicPlanners.jl with the rail
progress heuristic) on generated Kleine Binckhorst scenarios: 1 to 10 trains, servicing off and on, FIFO / LIFO /
random matching, a 1800 s budget per run. Requested by Issa; run on DAIC in November 2026. This directory has the
experiment definitions, the scripts that ran them, the raw results, and the provenance of what ran.

Status: complete. The first pass (5 instances per matching, 900 runs) and the extension (10 more instances per matching for
3 to 8 trains, 840 runs) are both in `results/issa_grid.csv` (1740 rows). `provenance.md` has the builds and job ids.

## Contents

| File | What it is |
|---|---|
| `issa_grid_servicing_{off,on}.json` | The grid: seed 700, trains 1 to 10, 5 instances x 3 matchings, `max_duration` 1800, `reject_infeasible` true, tools solver + enhsp + symbolic-rail. 450 tasks per variant. |
| `issa_grid_ext_servicing_{off,on}.json` | The same with `number_of_instances` 15. Instances 0 to 4 are identical to the grid's (the generator seeds an instance as `seed*(j+i+1)`, `j` being its train count's position in `number_of_trains`); the extension runs instances 5 to 14. |
| `issa_pilot_servicing_{off,on}.json` | The pilot: 2 and 10 trains, random matching, 1 instance. |
| `submit_grid.sh` | Submits one variant as generate -> one array per tool -> aggregate, with per-tool partition, memory and throttle, staging by train count and instance, and a pruned manifest for extensions. |
| `extract_csv.py` | Builds the CSV: one row per task of `tasks.tsv`, joined with the output directories and a `sacct` dump. |
| `summarise_outcomes.py` | Counts outcomes per variant, tool and train count from that CSV. |
| `submit_pilot.sh`, `pilot_report.sh`, `node_info.sbatch` | The pilot's resource arms (compute-p1, memory, DAIC), its report, and a node description job. |
| `provenance.md` | Builds, commits, experiment definitions and hardware. Its TODO items can only be read on DAIC. |
| `results/issa_grid.csv` | The result: first pass and extension, one row per run (1740). |
| `results/first_grid.csv` | The first pass alone, built with an earlier version of `extract_csv.py` (no `build` column; its 45 one-train servicing-on rows read `no_result` where `issa_grid.csv` has `no_scenario`). Superseded by `issa_grid.csv`. |
| `results/sacct_first_grid.txt`, `results/sacct_extension.txt` | The `sacct` dumps the CSV was joined with. |

Tests: `tests/test_issa_grid_scripts.py` (the extraction and the submit script, without a cluster).

## Running it

Everything below runs from the repo root of a checkout on the cluster. DAIC support (the site files under
`scripts/slurm/site/`, which the sbatch scripts source) is on branch `daic-port`, which was not merged into `main` when
this was written; the DAIC runs used `daic-port` with `main` merged in locally.

```bash
export SLURM_SITE=daic; source scripts/slurm/site/daic.env
module load 2026 cpu && module load "$PYTHON_MODULE"
python3 scripts/stage_apptainer_images.py --edge        # then do not restage while a grid is running
```

Memory per task on DAIC comes from the pilot (peak resident memory at 10 trains after 30 min: solver 0.6 to 0.9 GB,
symbolic-rail 5.4 to 5.8 GB, ENHSP 10.8 and 16.8 GB): solver 4G, symbolic-rail 12G, ENHSP 32G, one CPU each, 45 min
limit. These are the script's defaults when `SLURM_SITE=daic`. On DelftBlue's `compute-p1` (3900 MB per core) both
planners need more than that at 10 trains.

Stage 1, 1 to 6 trains, then the rest later on the same output directory:

```bash
G=experiments/issa-grid
TRAINS_MAX=6 $G/submit_grid.sh $G/issa_grid_servicing_off.json ~/linuxhome/issa/issa_grid_off ~/linuxhome/issa/issa_grid_off_results
TRAINS_MAX=6 $G/submit_grid.sh $G/issa_grid_servicing_on.json  ~/linuxhome/issa/issa_grid_on  ~/linuxhome/issa/issa_grid_on_results
# stage 2: the scenarios exist, tasks.tsv is reused as it is
TRAINS_MIN=7 SKIP_GENERATE=1 $G/submit_grid.sh $G/issa_grid_servicing_off.json ~/linuxhome/issa/issa_grid_off ~/linuxhome/issa/issa_grid_off_results
```

Notes that cost time to find:

- Never split the experiment into two JSON files by train count: the seeds change with the position in the list. Select
  with `TRAINS_MIN`/`TRAINS_MAX` (and `INSTANCE_MIN`/`INSTANCE_MAX`) instead; the numbering of `tasks.tsv` is
  deterministic, so all stages of one output directory share it.
- Servicing on at 1 train cannot be generated with `time_window_per_train` 1440 (the generator: not enough time to
  park and service one train with a servicing time of 300 and `min_gap_on_gateway` 480). Its generate job exits 1, and
  with the default `afterok` dependency DAIC cancels the arrays silently, without showing `DependencyNeverSatisfied`.
  Run servicing on from 2 trains (`TRAINS_MIN=2`, `SKIP_GENERATE=1` after generating), or use `GEN_DEP=afterany`.
- SLURM refuses array indices above `MaxArraySize` (1001 on DAIC). For an extension on a fresh output directory use
  `PRUNE_MANIFEST=1`, which keeps only the selected tasks in `tasks.tsv` and numbers them from 0. The extension used:
  `PRUNE_MANIFEST=1 TRAINS_MIN=3 TRAINS_MAX=8 INSTANCE_MIN=5 ENHSP_TRAINS_MAX=4 GENERATE_TIME=00:45:00`
  (`GEN_DEP=afterany` for servicing on), each variant on its own `issa_grid_ext_*` output directory.
- Do not rebuild `tasks.tsv` while arrays of the same directory run (a task starting in that moment reads the wrong
  row); `SKIP_GENERATE=1` reuses it for that reason.
- The submit script checks the partitions exist. Without `SLURM_SITE=daic` it defaults to DelftBlue's `compute-p1`.

## Building the CSV

```bash
# array ids: ~/issa_grid_jobs.txt has one line per submitted array, "<tool> <array id> <output dir>"
sacct -j ID1,ID2,... -P -n -o JobID,Partition,NodeList,Elapsed,MaxRSS,State > sacct.txt
python3 experiments/issa-grid/extract_csv.py --run off=<dir>:ID1,ID2,... --run on=<dir>:ID1,ID2,... --sacct sacct.txt -o issa_grid.csv
python3 experiments/issa-grid/summarise_outcomes.py issa_grid.csv
```

Several `--run` options with the same servicing label are fine (a grid and its extension). Every task of a
`tasks.tsv` gets a row, including one killed by the out-of-memory killer, which never writes `result.json`.

## The CSV

Issa's columns come first: `type-solver` (solver, enhsp, symbolic-rail), `num_trains`, `servicing` (off, on),
`matching-order`, `instance-num`, `runtime`, `expanded-states`, `solution-length`. Then:

- `valid`: the evaluator accepted the plan. Empty when there was no plan.
- `outcome`: `valid`, `invalid` (a plan the evaluator rejected; `reason` has its reason), `timeout` (budget used, no
  plan), `oom`, `crash` (non-zero exit without a plan), `no_plan`, `no_scenario` (the generator refused it), or
  `no_result` (no `result.json` and no explanation).
- `runtime`: wall time of the whole task in seconds, including container start-up.
- `solution-length`: the PDDL plan length for the planners, the number of actions of `plan.json` for the solver.
  `json_actions` is the latter for every tool.
- `expanded-states`: planners only. The solver has `solver_neighbors`, which is not the same thing.
- Planner stages: `pddl_conversion_s`, `search_s`, `json_conversion_s`, `validation_s`, `planner_process_s`, `total_s`.
  `search_s` is each planner's own search time and is **not comparable across planners**: ENHSP's "Planning Time"
  excludes JVM start-up, parsing and grounding, symbolic-rail's covers only the planner call and not Julia start-up.
  `planner_process_s` covers the whole planner subprocess for both and is the comparable one.
- Solver: `time_to_best_s` is when the final plan was found, `solver_feasible` the solver's own verdict. The solver stops
  at its first feasible plan; otherwise it runs the whole budget, so `runtime` is then the budget.
- `slurm_state`, `partition`, `node`, `maxrss_mb` from `sacct`; `build` is the version line the tool printed.

`no_scenario` rows (45: 1 train, servicing on) have no run, so empty runtime and build.

## Results (1740 rows: 1695 runs and 45 `no_scenario`)

Cells for 1 to 2 and 9 to 10 trains have 5 instances x 3 matchings per variant, 3 to 8 trains 15 x 3. Valid plans per tool
and train count, both variants pooled (servicing on has no 1-train cell, so n is 15 there; n is 30 at 2, 9 and 10 trains,
90 at 3 to 8 trains; ENHSP ran 3 and 4 trains only in the extension):

| trains | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|
| solver | 13/15 | 25/30 | 69/90 | 62/90 | 52/90 | 46/90 | 31/90 | 31/90 | 10/30 | 6/30 |
| symbolic-rail | 15/15 | 26/30 | 75/90 | 53/90 | 24/90 | 9/90 | 12/90 | 1/90 | 2/30 | 0/30 |
| enhsp | 15/15 | 24/30 | 54/90 | 16/90 | 0/30 | 0/30 | 0/30 | 0/30 | 0/30 | 0/30 |

Paired by instance (solver against symbolic-rail), exact two-sided sign test on the discordant pairs. The three
matchings of one instance share their arrivals, so the pairs are not independent and the p-values are indicative.

| matching | trains | pairs | solver only valid | symbolic-rail only valid | p |
|---|---|---|---|---|---|
| FIFO | 1 to 10 | 215 | 78 | 1 | < 0.001 |
| LIFO | 1 to 10 | 215 | 68 | 1 | < 0.001 |
| random | 1 to 10 | 215 | 12 | 28 | 0.017 |
| random | 2 to 5 | 100 | 8 | 25 | 0.005 |
| random | 3 to 8 | 180 | 11 | 21 | 0.11 |

- The solver is clearly better with FIFO and LIFO matching. With random matching symbolic-rail is better at small to
  medium size (2 to 5 trains), and the two are about even from 5 trains. With servicing on, the random-matching
  difference is 2 against 10 (p = 0.039); with servicing off 10 against 18 (p = 0.18).
- ENHSP has no niche. It solves nothing from 5 trains. At 3 and 4 trains with random matching it loses to symbolic-rail
  (1 against 17, p < 0.001) and ties with the solver (10 pairs where only the solver is valid, 7 where only ENHSP is, p = 0.63).
- Servicing on lowers the valid rate at 3 to 6 trains: solver 132/180 off against 97/180 on, symbolic-rail 89/180
  against 72/180; ENHSP at 3 and 4 trains 44/90 against 26/90.
- No run ended out of memory and every task finished (`COMPLETED`). Peak resident memory: solver 2.2 GB, symbolic-rail
  7.5 GB, ENHSP 19.8 GB.
- The solver and the evaluator disagree in 82 of its 645 runs: 62 where the solver reports feasible and the evaluator
  rejects, 20 the other way round. The solver also fails 2 of the 15 one-train servicing-off scenarios that both
  planners solve.
- The solver returns a plan in every run, and in 238 of the 645 the solver itself reports infeasible (the budget ran out
  without a feasible plan; the evaluator then rejects it too). For example, 38 of 45 runs at 8 trains with servicing on.
  `solver_feasible` and `time_to_best_s` separate these from the 62 where solver and evaluator disagree.
- Four ENHSP runs at 3 trains with random matching ended with exit code 1 and no plan (`crash`); their logs were not
  examined.
- Total wall time of all runs: about 391 CPU-hours.
