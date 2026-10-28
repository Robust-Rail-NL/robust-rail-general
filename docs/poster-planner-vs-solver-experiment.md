# Reproducing the poster planner-vs-solver experiment

Documents exactly what was run for the robust-rail-planner poster (planner
vs solver, Location_KleineBinckhorst, 2026-10-14/15), and how to reproduce
or extend it. For the general SLURM/apptainer pipeline mechanics (staging,
manifest, array job, aggregation), see [docs/slurm-apptainer.md
](slurm-apptainer.md) — this doc only covers what's specific to this
experiment.

## What this is

Two sweeps over the identical 300-scenario set (1-5 trains x FIFO/LIFO/random
matching x 20 instances/cell), each running both `robust-rail-solver` and
`robust-rail-planner` against every scenario, differing only in the per-tool
wall-clock budget:

- `poster_planner_vs_solver.json` — `max_duration: 300`, the primary dataset.
- `poster_planner_vs_solver_600s.json` — `max_duration: 600`, otherwise
  identical (same seed, same `scenario_config`) — a directly comparable
  second dataset over the same 300 instances, run to check whether a longer
  planner budget recovers some of the 300s timeouts. **Not** a
  like-for-like comparison with any external 600s result that used a
  different scenario set or generator version — see "Known caveats" below.

A follow-up, `poster_planner_timing.json` (planner-only, 1-3 trains, 180
scenarios), investigates a start-of-sweep planner slowdown observed in both
sweeps — see "Known caveats."

## Image provenance

`stable` and `edge` are floating tags — the authoritative record of which
exact build produced any given attempt's result is the attempt's own stamp
file, not the tag name. The values below were read directly from the
completed 300s sweep's own stamps
(`<instance>/<local_search|planning>/run_stamp.json`,
`<instance>/<local_search|planning>/eval_stamp.json`,
`<instance>/scenario_<instance>.generator.json`):

| Tool | Version used | Image | `image_id` (apptainer `.sif` identity) |
|---|---|---|---|
| generator | `stable` | `ghcr.io/robust-rail-nl/generator:latest` | `sif:45088768:1792009591000000000` |
| solver | `stable` | `ghcr.io/robust-rail-nl/hip:latest` | `sif:78581760:1792009600000000000` |
| planner | `edge` | `ghcr.io/robust-rail-nl/planner:edge` | `sif:448696320:1792009671000000000` |
| evaluator | `stable` | `ghcr.io/robust-rail-nl/tors:latest` | `sif:31821824:1792009676000000000` |

`image_id` is `docker_utils.image_identity()`'s own format
(`sif:<size>:<mtime_ns>` of the cached `.sif`) — to confirm a currently
staged `.sif` is still the exact same one, compare against this table:

```bash
python3 -c "
import sys; sys.path.insert(0, '.')
from scripts.docker_utils import image_identity, DEFAULT_SIF_CACHE_DIR
for image in ['ghcr.io/robust-rail-nl/generator:latest',
              'ghcr.io/robust-rail-nl/hip:latest',
              'ghcr.io/robust-rail-nl/planner:edge',
              'ghcr.io/robust-rail-nl/tors:latest']:
    print(image, '->', image_identity('apptainer', image, DEFAULT_SIF_CACHE_DIR))
"
```

Known commit context (less authoritative than the table above — these
branches keep moving, so treat this as "what main/edge looked like around
the time of the run," not a guarantee):

- **planner**: branch `fix-whole-departure-and-arrival-options`, commit
  `77bf765` ("Document the Q1 planner experiment"), merged into
  `robust-rail-planner` `main` and `edge` 2026-10-15.
- **generator**: `robust-rail-generator` `main` at `5de5eb4` (version 2.2.0)
  as observed 2026-10-14.
- **solver**: `robust-rail-solver` `main`, including PR #72
  ("exact-mm-lengths") — `robust-rail-solver` `edge` did **not** have this
  fix as of this run, which is why solver/evaluator were pinned to `stable`
  rather than `edge` for this experiment (running them on `edge` would have
  reintroduced the length-truncation mismatch that fix was for).
- **evaluator**: `robust-rail-evaluator` `main`, including PR #40
  ("issue-39-mm-lengths"), the evaluator-side half of the same fix.
  `robust-rail-evaluator` `main` has moved further since (at least one more
  merge, `docker-push-deps`) — if `stable` is re-staged today, verify its
  `image_id` against the table above before trusting results as comparable
  to this run's.

## Prerequisites

Everything in [docs/slurm-apptainer.md](slurm-apptainer.md) — DelftBlue
module loads, `scripts/stage_apptainer_images.py --edge` (needed for the
planner's `edge` version; the digest-check added 2026-10-14 means re-running
it is always safe and a no-op if nothing's moved), the account/partition
facts, and the general "Running a sweep" workflow. This doc assumes that's
already set up and just gives the exact commands for *this* experiment.

## Running the 300s sweep

```bash
python3 scripts/slurm_manifest.py poster_planner_vs_solver.json \
    --output-dir /scratch/$USER/poster-experiments

sbatch scripts/slurm/generate_scenarios.sbatch poster_planner_vs_solver.json \
    /scratch/$USER/poster-experiments
# wait for that job (squeue -u $USER), then:

sbatch --array=0-599 scripts/slurm/run_experiment_array.sbatch \
    /scratch/$USER/poster-experiments/tasks.tsv \
    poster_planner_vs_solver.json \
    /scratch/$USER/poster-experiments

# once the array job's ID is known:
sbatch --dependency=afterok:<array_job_id> scripts/slurm/aggregate.sbatch \
    /scratch/$USER/poster-experiments ~/poster-results
```

No `--time` override needed — `scripts/slurm/run_experiment_array.sbatch`'s
own `--time=00:08:00` default was sized for exactly this 300s budget.

## Running the 600s sweep

Same shape, but two things differ, both load-bearing:

1. **Separate `--output-dir` and home-dest from the 300s run** —
   `run_experiment`'s own stamp-based reuse keys on (tool, scenario, image,
   `max_duration`); reusing the 300s run's output-dir would see the
   mismatched `max_duration`, treat the existing 300s results as stale, and
   `rmtree` them before rerunning — destroying the 300s data rather than
   extending it.
2. **`--time` must be overridden on the array submission** — the template's
   `--time=00:08:00` default would walltime-kill any task that genuinely
   uses the full 600s budget, before the tool's own internal timeout even
   fires. A SLURM walltime-kill is *worse* than a clean timeout here:
   `run_experiment`'s reuse logic treats a kill-from-outside as unusable,
   not just a recorded failure.

```bash
python3 scripts/slurm_manifest.py poster_planner_vs_solver_600s.json \
    --output-dir /scratch/$USER/poster-experiments-600s

sbatch scripts/slurm/generate_scenarios.sbatch poster_planner_vs_solver_600s.json \
    /scratch/$USER/poster-experiments-600s
# wait for that job, then:

sbatch --time=00:15:00 --array=0-599 scripts/slurm/run_experiment_array.sbatch \
    /scratch/$USER/poster-experiments-600s/tasks.tsv \
    poster_planner_vs_solver_600s.json \
    /scratch/$USER/poster-experiments-600s

sbatch --dependency=afterok:<array_job_id> scripts/slurm/aggregate.sbatch \
    /scratch/$USER/poster-experiments-600s ~/poster-results-600s
```

## Accessing results

Each aggregation job's home-dest (`~/poster-results`, `~/poster-results-600s`)
holds `runs.csv`, `feasibility.csv`, `solver_failures.csv`,
`planner_failures.csv`, `coverage_analysis.txt`, `experiment.json`, and the
full per-instance tree (`scenario_<instance>.json`, `plan.json`,
`result.json`, `eval_result.json`, stamps). From a machine with DelftBlue SSH
access, either `scp` the summary files directly, or mount the whole
directory read-only for browsing:

```bash
sshfs -o ro leonplanken@login.delftblue.tudelft.nl:poster-results ~/mnt
```

## Interpretation conventions

- **Feasibility denominator**: `feasibility.csv`'s `classification` column
  separates `feasible` (something solved it) from `infeasible` (a
  scenario-level rejection — `"Issue detected with the Scenario"` in some
  attempt's `eval.out`/`eval.err`, independent of which tool ran) from
  `unresolved` (neither). For the 300s sweep specifically, `infeasible` was
  **0/300** — the plain 300-scenario denominator is honest as-is for this
  run. This isn't guaranteed to hold for every run; always check
  `feasibility.csv`'s own counts before assuming the denominator needs no
  adjustment, and filter `infeasible` out (reporting its count as a
  footnote) if it's ever non-zero.
- **Failure causes**: `solver_failures.csv`/`planner_failures.csv`'s
  `reason` column distinguishes `"timed out after Ns"` cleanly, and extracts
  a specific evaluator-rejection reason in two cases
  (`run_evaluator.py`'s `_classify_verdict`: a scenario-level issue, or a
  `"Scenario failed ... The action is invalid."` pattern). Anything else
  falls back to the generic `"plan rejected"` — in the 300s sweep this was
  33/64 of solver's failures and 33/61 of planner's, i.e. over half of each
  tool's failures carry no specific reason from this pipeline alone.
  `robust-rail-planner`'s own `eval.txt`-parsing script (not part of this
  repo) fills that gap for a full failure-cause breakdown.

## Known caveats

- **Start-of-sweep planner slowdown**: planner wall time in both sweeps
  shows a cold-start effect concentrated in whichever tasks SLURM dispatches
  first (tasks dispatch roughly in ascending array index order as slots free
  up, and the manifest's row order happens to group by train count — so the
  earliest-dispatched tasks were disproportionately 1-train cells). Not a
  property of the scenarios themselves. Root-caused by a dedicated probe —
  see "Cold-start root cause" below.
- **Track 906a**: both tools hit rejections referencing the same track, with
  different wording — planner: `"Track 906a is reserved"`; solver:
  `"Parking is not allowed on track 906a"`. Flagged to the planner team;
  not yet root-caused as of this writing.
- **600s vs 300s is a lower-bound comparison, not a budget-controlled
  experiment**: both sweeps used identical scenarios and `max_duration` was
  the only deliberate difference, so a difference in outcomes reflects the
  budget — but no attempt was made to isolate budget effects from the
  planner's own cold-start effect above, which affects both sweeps to
  different degrees (stronger in the 300s sweep: 25/25 of the first-minute
  tasks were slow, vs 7/25 in the 600s sweep).

## Cold-start root cause (2026-10-27)

Root-caused via a dedicated probe (`__scratch/run_cold_start_probe.py`,
gitignored, not in this repo's tracked history — see
`__scratch/cold-start-probe-state-of-play.md` for the full build/debug
history if revisiting this), run against one representative scenario
(`custom_1_FIFO_0`) from the 300s sweep's own scenario set. Four
conditions, each gated on an empirically-cold starting state (a single-run
canary confirmed >=45s wall before the real measurement, matching this
sweep's own slow/fast split):

- **(a)** one cold run — baseline.
- **(b)** 25 simultaneous runs reading the `.sif` from the shared staging
  cache (`~/apptainer-images`), same as a real sweep — `--exclusive`
  SLURM allocation so each task genuinely owns a whole node (no
  co-scheduled CPU contention), with SLURM reusing a node sequentially,
  one task at a time, once a prior task's exclusive allocation on it frees
  up.
- **(c)** 25 simultaneous runs, each first copying the `.sif` to
  node-local storage (`$TMPDIR`) before running from that copy.
- **(d)** 25 simultaneous runs, each doing one throwaway self-warmup run
  immediately before its own timed run.

Time to the planner's own `"Planning..."` line / total wall, split by
whether the task was the first to use its node or reused one an earlier
task in the same condition had already touched:

| Condition | First use of a node | Later reuse of same node |
|---|---|---|
| (a) baseline | 44.6s / 53.0s (1 node) | — |
| (b) shared storage | 40.2–41.5s / 48.8–49.9s (4 nodes) | avg 11.1s / 19.5s (n=21) |
| (c) local copy | 9.7s *or* 36.7s / 18.1s *or* 45.1s (2 nodes — see below) | avg 9.8s / 18.1s (n=23) |
| (d) self-warmup | 9.9–10.1s / 18.0–18.2s (3 nodes, incl. one touched nowhere else in the run) | avg 10.0s / 18.1s (n=22) |

Findings:

- **The slowdown is per physical node, not per condition.** With
  `--exclusive` isolating each task to its own node, the first task to
  land on any given node is slow (~40–45s to-planning) regardless of
  condition, and every later task reusing that same node is fast (~10s
  to-planning) — a clean ~2.5x gap with no overlap, closely matching the
  poster sweeps' own early/late split.
- **Copying the `.sif` to node-local storage (condition c) does not fix
  it.** A genuinely fresh node (task 10, `cmp205`) was still cold (36.7s)
  even after the local copy; the one fast "first use" in that condition
  (`cmp058`, 9.7s) only looks fast because that node had already been
  warmed moments earlier by condition (b)'s own tasks — the warmth is
  node-level state that outlives a single condition, not something
  condition (c)'s fix produced. The copy itself is also fast (0.4–1.9s
  for the ~430MB image), so shared-storage read latency isn't the
  bottleneck either.
- **A throwaway self-warmup run per task (condition d) fully eliminates
  the cold cost**, even on a node touched nowhere else in the whole run
  (`cmp044`).
- **Conclusion**: whatever makes a node's first apptainer invocation slow
  (most likely OS-level page cache / squashfs loop-mount setup, or
  something Julia populates against local disk on first use — not pinned
  down further than that) is populated by *any* apptainer invocation on
  that node, not specifically by having the `.sif` stored locally. The
  actionable fix for a real sweep is a cheap warmup run per node before
  the timed runs, not a node-local `.sif` copy.

Caveats: single run, single scenario, only 2–4 cold (first-node-use)
observations per condition (one per distinct node visited) — worth
replicating before treating as final, though the gap is large and
consistent enough to act on.
