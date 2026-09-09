# Pipeline integration testing: comparing `stable`, `edge` and `local`

Each `run_*.py` script (and `run_pipeline.py`, which drives all of them) takes
`--version` to pick which Docker images to run: `stable` (published, `docker
pull`ed once up front so a floating tag is never served stale), `stable-assert`
(evaluator with assertions, for catching corrupt-state verdicts rather than
comparing baselines), `edge` (the solver's and evaluator's not-yet-reviewed
channel; the generator has no `edge` channel and stays on `stable`), and `local` (bare tags — `generator:latest`,
`hip:latest`, `tors:latest`, `planner:latest` — built and tagged on this
machine, never pulled). This doc is about using `local` to verify a fix before
it goes anywhere near `edge` or `stable`.

`stable-assert` only swaps the evaluator's image; the solver stays on the
plain `hip` image even under `stable-assert`. The solver is a
wall-clock-bounded local search, so an assertions-enabled build explores less
of the neighbourhood in the same budget and can return a structurally
different plan on any scenario that doesn't converge first — which would
break the plan-diff comparison this doc relies on. The solver's `-assert`
image is instead run separately as a soak test (seed sweeps looking for a
violation, via `sweep_seeds.py`), never as part of a `stable`/`edge`/`local`
pipeline comparison. See the `stable-assert` entry in `run_solver.py`'s
`DOCKER_IMAGE_VERSIONS` for the full reasoning.

## The `local-edge` branch convention

There is no dedicated channel for "several open, unreviewed PRs across
multiple repos, checked together." When that's what's needed, build a
`local-edge` branch per affected repo — `git merge --no-ff` each open bugfix
branch on top of that repo's `edge` — then `docker build` it locally under the
bare tag its `run_*.py` script's `local` entry expects, and run the pipeline
with `--version local`.

This is one level more provisional than `edge`: nothing on `local-edge` has
been reviewed, it is never pushed anywhere, and it exists only on whichever
machine built it. Treat a `local-edge` result as "this fix looks right and
doesn't regress the fixture corpus," never as a substitute for review, and
never cite it as if it were a tagged or pushed image. See
[`roadmap-2.0.0.md`](roadmap-2.0.0.md#solver13-verified-fixed-on-local-edge-6t_custom_example3-now-valid)
for a worked example.

## Running a comparison

1. Confirm the tree is clean (`git status`) — the fixture corpus's `.json`
   files (`scenarios/scenario_*.json`, `plans/plan_*.json`) are tracked, so a
   pipeline run overwrites them in place.
2. Run the baseline: `python3 run_pipeline.py --version stable` (or `edge`),
   with no `--location`, so nothing in the corpus is skipped.
3. Snapshot `scenarios/`, `plans/` and `evaluations/` for every `Location_*`
   somewhere outside the repo. Do this even though the `.json` files are
   tracked: their companions (`.out`, `.err`, `.txt`, and all of
   `evaluations/`) are gitignored, so `git diff` alone won't show them, and
   the next run overwrites them with no record kept.
4. Run the comparison target: `python3 run_pipeline.py --version local`.
5. Compare, per scenario:
   - **Verdict** — the primary signal. `evaluations/eval_<name>.out` ends
     with `The plan is valid` or `The plan is not valid`. A scenario the
     evaluator rejects before considering any plan (an infeasible proof, e.g.
     a train longer than the track it arrives on) instead exits nonzero with
     nothing written to `eval_<name>.txt` — check `eval_<name>.err` for the
     reason.
   - **Plan content** — `diff plans/plan_<name>.json` between the two runs.
     The solver can produce a structurally different plan without the verdict
     changing (observed for 7 of 12 fixtures in the 2026-09-04 check above),
     which is worth noting even when it isn't the thing being verified.
6. Restore the tracked files to the baseline snapshot (or `git checkout --`
   them) so the working tree ends clean. The committed fixture corpus should
   never end up parked on non-`stable` output.

## Reading `run_pipeline.py`'s exit status

`run_evaluator.py` exits 1, and `run_pipeline.py` reports "Pipeline aborted:
step 'evaluator' failed", whenever *any* plan in the run is invalid or
infeasible. For this fixture corpus that is expected on every run — 4 of the
12 scenarios are permanently infeasible by design (see
[`scenario-feasibility.md`](scenario-feasibility.md)), and more are
known-`unknown`. The abort message does not mean the step stopped partway:
`run_evaluator.py` finishes evaluating every plan before exiting. Check the
`Done: N/12 succeeded` line and the per-scenario verdicts, not the pipeline's
overall exit code.

## Interpreting results

- [`scenario-feasibility.md`](scenario-feasibility.md) — the expected outcome
  for every fixture scenario under `stable`, and the classification scheme
  (`feasible` / `infeasible` / `unknown` / `generator`).
- [`roadmap-2.0.0.md`](roadmap-2.0.0.md) — known solver/evaluator defects,
  which scenarios they block, and their fix status per channel.
