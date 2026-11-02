# Cold-start probe

Scripts behind the planner cold-start root-cause finding in
[docs/poster-planner-vs-solver-experiment.md](../../docs/poster-planner-vs-solver-experiment.md#cold-start-root-cause-2026-10-27)
("Cold-start root cause" section) — read that first for the actual
findings and methodology. This README just orients you among the files.

Entry point: `run_cold_start_probe.py`. Run from the repo root (its own
docstring has the full usage/options):

```bash
sbatch scripts/cold_start_probe/run_cold_start_probe.sbatch <SCENARIO.json> <OUT_BASE>
```

It orchestrates the whole 4-condition probe end to end: resubmits a cheap
canary (`planner-timing-single.sbatch`) until the cache reads as cold,
then runs the matching 25-task array (`planner-timing-array.sbatch`) for
each of conditions (b)/(c)/(d), and finally summarizes everything into one
CSV. Resumable against the same `--out-base` if interrupted.

| File | Role |
|---|---|
| `run_cold_start_probe.py` | Orchestrator — drives the whole probe, resumable, PID-locked against a second concurrent instance, verifies each SLURM job via `sacct` rather than trusting `squeue` alone. |
| `run_cold_start_probe.sbatch` | Submits the orchestrator itself as a SLURM job (not a login-node process) so it isn't tied to one login node or session. |
| `run_planner_direct.py` | Invokes `apptainer` directly (bypassing `run_planner.py`, which swallows the container's own stdout/stderr) so the planner's real phase timestamps are visible. Used by both `.sbatch` scripts below. |
| `planner-timing-single.sbatch` | Condition (a) — one direct run; also doubles as the "is the cache cold yet" canary for conditions (b)/(c)/(d). |
| `planner-timing-array.sbatch` | Conditions (b)/(c)/(d) — a 25-task `--exclusive` array, parameterized by `MODE` (`shared`/`local`/`warmup`). |
| `summarize_planner_timing.py` | Parses all conditions' output directories into one CSV. |

None of these are part of the regular sweep pipeline
(`scripts/slurm/*.sbatch`) — they're a one-off diagnostic tool, kept here
in case the finding needs re-verifying later (e.g. once a warmup fix is
implemented — see [issue #28](https://github.com/Robust-Rail-NL/robust-rail-general/issues/28)).
