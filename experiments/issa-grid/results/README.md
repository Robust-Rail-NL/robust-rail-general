# Results of the solver / ENHSP / symbolic-rail grid

For Issa. `issa_grid.csv` has one row per run: 1740 rows, of which 1695 are runs and 45 are cells that cannot exist
(see "Reading the CSV"). The runs took place on DAIC on 2026-11-07 and 2026-11-08. What ran, with builds and job ids, is
in `../provenance.md`; how to rerun it is in `../README.md`.

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
