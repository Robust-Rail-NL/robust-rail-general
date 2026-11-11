# Results of the solver / ENHSP / symbolic-rail grid

For Issa. `issa_grid.csv` has one row per run: 1740 rows, of which 1695 are runs and 45 are cells that cannot exist
(see "Reading the CSV"). The runs took place on DAIC on 2026-11-07 and 2026-11-08. What ran, with builds and job ids, is
in `../provenance.md`; how to rerun it is in `../README.md`. The builds that ran were edge builds; they correspond to the
releases solver 2.3.0, planner 0.6.0, evaluator 2.4.0 and generator 2.5.0 (see "Released versions" in `../provenance.md`).

## What was run

- Scenarios: generated Kleine Binckhorst scenarios (generator v2.5.0, seed 700), 1 to 10 trains, servicing off and on,
  FIFO / LIFO / random matching order, `reject_infeasible` on (the generator only keeps scenarios it can show to be
  feasible).
- Tools: the HIP solver (`solver`), ENHSP (`enhsp`) and symbolic-rail, the last two through the planner pipeline.
  Every run has a 1800 s budget, one CPU, and memory of 4 GB (solver), 12 GB (symbolic-rail) or 32 GB (ENHSP).
- Instances per cell (tool x servicing x trains x matching): 5, and 15 for 3 to 8 trains (the first pass ran 5, the
  extension 10 more). ENHSP ran 1 to 10 trains in the first pass but only 3 and 4 trains in the extension, because it
  solves nothing from 5 trains on. Its cells at 5 to 8 trains have 5 instances, the others 15.
- A run counts as **valid** when the evaluator (TORS) accepts the plan the tool produced.

## Reading the CSV

Your columns come first: `type-solver`, `num_trains`, `servicing`, `matching-order`, `instance-num`, `runtime`,
`expanded-states`, `solution-length`. Then:

- `outcome` is the single column to filter on: `valid`, `invalid` (plan rejected by the evaluator; `reason` says why),
  `timeout` (budget used, no plan), `crash` (the tool exited with an error and no plan), `no_scenario`.
- `runtime` is wall time of the whole task in seconds, including container start-up. The solver stops at its first
  feasible plan and otherwise uses the whole budget, so its `runtime` is 1800 or less than that.
- `solution-length` is the PDDL plan length for the planners and the number of actions of the JSON plan for the solver.
  Those are different units; `json_actions` has the JSON action count for every tool.
- `expanded-states` exists for the planners only. The solver has `solver_neighbors`, which is not the same.
- Timings: `search_s` is each planner's own search time and is not comparable between ENHSP and symbolic-rail (ENHSP's
  excludes JVM start-up, parsing and grounding). Use `planner_process_s` to compare them. For the solver,
  `time_to_best_s` is when the final plan was found and `solver_feasible` is the solver's own verdict.
- `maxrss_mb`, `node`, `slurm_state` come from the cluster's accounting. `build` is the version line of the tool.

Two things to watch when you aggregate:

1. **Servicing on has no 1-train cell.** The generator refuses it (not enough time to park and service one train in the
   1440 window), so those 45 rows are `no_scenario` with empty runtime. Drop them before computing anything.
2. **The solver always returns a plan.** An `invalid` solver row is often a run that never found a feasible plan
   (`solver_feasible` is `false`, 238 of its 645 runs); it is not necessarily a bug. For "did it solve it", use
   `outcome == valid`.

## Hardware and measurement conditions

For the methods section of a thesis chapter. All 1695 runs ran on DAIC (TU Delft), partition `daic-eemcs-st`, on five
nodes that are identical in the parts that matter here (output of `lscpu` and `free` on each, jobs 123823 to 123827):

| property | value |
|---|---|
| CPU | Intel Xeon 6724P, 32 logical CPUs per node, 800 MHz minimum and 4300 MHz maximum clock, L3 cache 144 MiB (2 instances) |
| memory | about 512 GB per node (515648 MiB) |
| nodes used | gpu47 (451 runs), gpu48 (139), gpu49 (255), gpu51 (194), gpu52 (656); the `node` column has the node of every run |
| allocation per run | 1 CPU and 4 GB (solver), 12 GB (symbolic-rail) or 32 GB (ENHSP); each run in its own Apptainer container |
| time limits | 1800 s budget per tool, 45 min SLURM limit per task (the limit never hit) |

The nodes are GPU nodes, but no run asked for or used a GPU. A run is one process on one CPU.

Things to state next to wall-clock numbers:

- **The nodes are shared.** Up to 20 tasks per tool ran at once (account limit 64 running jobs), on nodes that other users
  of the partition also used, so a run may share caches and memory bandwidth with neighbours (the `free` output of the five nodes shows other
  jobs using 9 to 33 GB at the time). I did not measure the run-to-run spread of identical runs. `runtime` includes container
  start-up and, for the planners, Julia or JVM start-up; use `planner_process_s` and `time_to_best_s` for the tools' own work.
- **The five nodes have the same CPU model**, so the `node` column is not a source of systematic differences between
  tools. The CPU frequency was at 96 to 100 % of its maximum at the time of the `lscpu` check, i.e. the nodes were not
  throttled.
- **Absolute times do not transfer to other machines.** In a small pilot (2-train scenarios, same plans and the same
  numbers of expanded states) a node of TU Delft's DelftBlue cluster (Intel Xeon Gold 6248R at 3.0 GHz base and 4.0 GHz maximum, 48 logical CPUs; `compute-p1` nodes cmp012 and cmp014 with 192 GB, `memory` node mem006 with 768 GB) was about 1.4 to 1.6 times slower than a DAIC node on
  the stable parts of a run (PDDL conversion 0.39 to 0.47 s there against 0.29 to 0.34 s, validation 1.2 to 1.6 s against
  0.8 to 1.1 s). A tool that finds a plan after 1500 s on DAIC may not find it within 1800 s on DelftBlue. The
  comparison between tools on one cluster is not affected. That pilot has 6 tasks per cluster, so the ratio is rough.
- The solver's own search is also time-based (its budget is in seconds), so its result depends on CPU speed in the
  same way as the planners'.

## Findings

Valid plans, both servicing variants pooled (n is 90 per tool for 3 to 8 trains, 30 for 2, 9 and 10 trains, 15 for 1
train; ENHSP has 30 at 5 to 8 trains):

| trains | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|
| solver | 13/15 | 25/30 | 69/90 | 62/90 | 52/90 | 46/90 | 31/90 | 31/90 | 10/30 | 6/30 |
| symbolic-rail | 15/15 | 26/30 | 75/90 | 53/90 | 24/90 | 9/90 | 12/90 | 1/90 | 2/30 | 0/30 |
| enhsp | 15/15 | 24/30 | 54/90 | 16/90 | 0/30 | 0/30 | 0/30 | 0/30 | 0/30 | 0/30 |

1. **Matching order decides who wins.** With FIFO or LIFO matching the solver is clearly better (instances only the
   solver solves against only symbolic-rail: 78 against 1 for FIFO, 68 against 1 for LIFO). With random matching
   symbolic-rail is better at 2 to 5 trains (25 against 8, exact sign test p = 0.005) and the two are about even above
   that. Those pairs share arrivals across the three matchings, so read the p-values as indicative.
2. **Symbolic-rail's niche is small**: random matching, up to about 5 trains. From 6 trains it solves few scenarios
   whatever the matching, and with servicing on none at 7 trains and up.
3. **ENHSP has no niche.** It solves nothing from 5 trains and, with random matching at 3 and 4 trains, it is clearly
   behind symbolic-rail (valid in only 1 pair where symbolic-rail is not, against 17 the other way) and level with the
   solver (7 against 10).
4. **Servicing makes it harder** at 3 to 6 trains for every tool (solver 132 of 180 valid without servicing, 97 with;
   symbolic-rail 89 and 72; ENHSP at 3 and 4 trains 44 and 26 of 90).
5. **Resources**: no run ran out of memory. Peak memory was 2.2 GB (solver), 7.5 GB (symbolic-rail) and 19.8 GB (ENHSP).

## Open points

- In 82 of the solver's 645 runs, solver and evaluator disagree about feasibility (62 solver feasible and evaluator
  rejects, 20 the other way round). Valid-plan counts above go by the evaluator.
- The solver fails 2 of the 15 one-train servicing-off scenarios that both planners solve.
- Four ENHSP runs (3 trains, random matching; servicing off instances 0, 2, 4 and servicing on instance 2) are the `crash`
  rows: ENHSP exhausted its search after about 6 s ("Problem unsolvable", dead ends) and the planner exited with an
  error. Symbolic-rail timed out and the solver found no valid plan on the same four scenarios, so they may be hard or
  infeasible after all.
- Seven ENHSP plans were rejected with "Shunting unit with trains 1-0 not found" (a `BeginMove` that refers to a unit the
  evaluator does not know). Twelve plans from all three tools (6 symbolic-rail, 4 ENHSP, 2 solver) were rejected with
  "Track 906a is reserved". Issues for these are being drafted separately.
- A single seed family (700) and one generator configuration: the numbers say how the tools compare on these
  scenarios, not how they scale on other instance families.
