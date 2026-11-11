# Release notes

## 0.3.0 — 2026-11-11

Since 0.2.0 this repo gained a way to run the pipeline on SLURM clusters (DelftBlue and DAIC), a single-file description of an experiment, and the solver-versus-planners grid, a comparison of the HIP solver with the ENHSP and symbolic-rail planners with its results. The interchange schema is unchanged: `schemaVersion` stays 2, and the changes to `robust_rail_models` are additive.

### Scenario-config model: `reject_infeasible` (additive)

`TrainUnitDistribution` gains an optional boolean `reject_infeasible`
(`schema_scenario_config.json` regenerated), matching the generator option of
the same name (generator 2.5.0): with it on, a drawn scenario that violates a
necessary servicing bound is redrawn. `scripts/generate_experiment_configs.py`
accepts it as a `scenario_config` key and as `--reject-infeasible` /
`--no-reject-infeasible`; it is written to the generated config only when set,
so existing sweeps' configs do not change. Without it in this model a config
carrying the key is rejected. (#36)

### Scenario-config model: `servicing_per_composition` (additive)

`TrainUnitDistribution` gains an optional boolean `servicing_per_composition`
(`schema_scenario_config.json` regenerated), matching the new generator option
of the same name. `scripts/generate_experiment_configs.py` accepts it as a
`scenario_config` key and as `--servicing-per-composition` /
`--no-servicing-per-composition`; it is written to the generated config only
when set, so existing sweeps' configs do not change. Without it in this model
a config carrying the key is rejected. (#34)

### Servicing knobs in an experiment's `scenario_config` (#27)

`servicing_ratio` and `tasks_per_train_unit` are valid generator inputs, but the sweep config generator rejected them as unknown keys and never wrote them, so every servicing sweep ran with the generator's defaults (0.5 and 1). They are now accepted in `scenario_config` and as `--servicing-ratio` / `--tasks-per-train-unit`, and written to `train_unit_distribution` only when set. Existing sweeps generate the same configs as before.

### Running on SLURM clusters

- **Apptainer engine (#18).** `run_generator.py`, `run_solver.py`, `run_planner.py`, `run_evaluator.py` and `run_experiment.py` take `--engine apptainer` and `--sif-cache-dir`, for clusters whose compute nodes have no Docker daemon. Docker stays the default; a normal local run is unchanged. `scripts/stage_apptainer_images.py` stages the images a sweep needs into a shared `.sif` cache from the login node, and `scripts/slurm_manifest.py`, `scripts/slurm_run_task.py` and `scripts/slurm/*.sbatch` turn a sweep into a job array with one attempt per task. Three bugs surfaced on the first cluster runs and are fixed: `apptainer exec` does not run an image's Docker `ENTRYPOINT`; Apptainer uses the host's working directory instead of the image's `WORKDIR` (fixed with `--pwd`); and a `.sif` is read-only, which made the solver's scratch writes crash (fixed with `--writable-tmpfs`). The timeout handling also had a latent bug (`Popen.wait(timeout=...)` does not kill the child), which is fixed. Details and rationale: `docs/slurm-apptainer.md`.
- **One config file per experiment (#23).** An experiment is one JSON file (name, location, tools, planner variant, time budget, seeds, image versions, departure delay, scenario sweep); see `example_experiment.json`. `python run_experiment.py example_experiment.json` runs it, and the SLURM scripts read the same file, so a local run and an array run produce the same folder layout. Everything a run creates goes under `results/<name>/`. The planner variant can be chosen (`symbolic`, `symbolic-rail` or `enhsp`), and instances run and are evaluated smallest first. The solver configs and all example plans and scenarios were moved to the v2 format.
- **Stage digest check (#24).** The staged tags (`stable`, `edge`) are floating, so a cached `.sif` did not prove that it still matched the tag. Staging now compares ghcr.io's current manifest digest for the tag with a `<sif>.digest` file written at the last pull, and pulls again when they differ, the file is missing or the registry cannot be reached. `--skip-existing` skips a `.sif` that is already present without asking the registry.
- **Several planners per experiment (#35).** An experiment's `planner` can be a list, and the sweep runs, reports and array-jobs each of them. The coverage analysis gained planner-versus-planner sections.
- **Poster experiment (#25).** `poster_planner_vs_solver.json` and the array and aggregate batch scripts for the planner-versus-solver comparison of the poster.
- **Cold-start probe (#33).** `scripts/cold_start_probe/` holds the scripts that measure how much of a planner run is start-up and how much is search.
- **DAIC (#37).** The SLURM sweeps also run on DAIC (partition `daic-eemcs-st`) alongside DelftBlue, with per-cluster site files, a `submit_sweep.sh` that chains manifest, generate, array and aggregate jobs, and notes on what was observed on DAIC (home quota, memory per task). See `docs/slurm-apptainer.md`.

### Facility `timeWindow` documented (#32)

Description-only change to the model, no `schemaVersion` bump: an absent or null `Facility.timeWindow` means the facility is available for the whole scenario, a present window constrains when service actions may run, and `end` is inclusive. The evaluator matches this since 2.4.0 (its #47), the solver already did. See `SCHEMA_CHANGELOG.md`, "Unversioned — 2026-10-28".

### Kleine Binckhorst: parking on the wash track (#31)

`Location_KleineBinckhorst/location.json` now sets `parkingAllowed` to true on track 63, the track of the Wasmachine (wash) facility. Before, a unit could not park there.

### The solver-versus-planners grid (#38)

`experiments/issa-grid/` compares the HIP solver, ENHSP and symbolic-rail on generated Kleine Binckhorst scenarios (1 to 10 trains, servicing off and on, FIFO / LIFO / random matching, 5 instances per cell, plus an extension to 15 instances for 3 to 8 trains) with an 1800 s budget per run. It contains the experiment definitions, the scripts that stage, submit and extract, their tests, `provenance.md` (what ran, with image digests and job ids), and `results/` with the CSV (1740 rows) and a README for the reader of the results. The first-pass results, hardware (DAIC and DelftBlue CPU models) and measurement conditions are described there.

Tool versions: the grid ran edge images that correspond to solver 2.3.0, planner 0.6.0, evaluator 2.4.0 and generator 2.5.0 (each release differs from the commit that ran only in version and release-notes files; see `provenance.md`).

### Compatibility

`schemaVersion` 2, unchanged. The model additions are optional keys; existing configs, scenarios and plans stay valid. The scripts' defaults are unchanged: Docker stays the default engine.

### Known gaps found by the solver-versus-planners grid

Four defects found while building the grid are tracked in the sibling repos, not here: robust-rail-planner #61 and #62, robust-rail-evaluator #51, robust-rail-solver #80. The grid's results include the runs affected by them.

## 0.2.0 — 2026-09-25

Defines interchange `schemaVersion: 2`. Full detail, including the
not-yet-universal-adoption caveat below, is in
[`SCHEMA_CHANGELOG.md`](SCHEMA_CHANGELOG.md#2--2026-09-24).

### `PredefinedTaskType.Reverse` (breaking)

A shunting unit reversing direction in place is now its own explicit action,
replacing a reversal that used to be silently embedded in a `Move`'s route
(the same track revisited two hops apart). A plan declaring
`schemaVersion: 2` or later must use `Reverse`; one declaring `1` (or none)
keeps evaluating exactly as before, with a deprecation warning.

### `Plan.feasibility` / `origin` / `cost` / `costDetails` (additive)

- `feasibility` (`Feasible`/`Infeasible`/`Unknown`, default `Unknown`) — a
  plan's own declared verdict on whether it satisfies all hard constraints,
  not a claim about whether some other plan for the scenario exists.
- `origin` (free text, e.g. `"robust-rail-solver 2.0.0-edge+20260826.a1b2c3d"`)
  — what produced the plan, for a human debugging a failed evaluation.
- `cost` (number) and `costDetails` (free-form breakdown string, e.g. the
  solver's own `SolutionCost.ToString()` output).

All default to absent/`Unknown`, so no existing plan fixture needs
migrating. The evaluator additionally logs a line (never a reject) when a
plan's declared `feasibility` disagrees with its own verdict.

### Downstream adoption, as of this release

`robust-rail-solver` and `robust-rail-evaluator` `main` both already
emit/parse the above. `robust-rail-planner` hasn't adopted either half yet —
not a blocker, since a `schemaVersion: 1` plan keeps evaluating exactly as
before in the meantime.

## 2.0.0 — 2026-08-20

This repo's slice of the shared 2.0.0 release: the same interchange format,
tagged together, across `robust-rail-generator`, `robust-rail-solver` (HIP) and
`robust-rail-evaluator` (TORS). This repo is the integration harness — the
pipeline scripts, the fixture corpus, and the location data those tools run
against. The full cross-repo picture — verification evidence, what each repo
changed, and the decisions behind the schema — lives in
[`docs/roadmap-2.0.0.md`](docs/roadmap-2.0.0.md).

### One file per artifact, not two

`location_solver.json` and `scenario_solver_*.json` are gone. Every location,
scenario and plan is now a single file in the unified interchange format,
consumed by all three tools directly:

- `location_unified.json` was renamed to `location.json`
- `run_solver.py` reads `scenario_*.json` instead of `scenario_solver_*.json`
- `run_planner.py` reads `location.json` instead of `location_solver.json`

`README.md` has been rewritten to match; it previously still documented the
two-file world.

### Known limitation: two canonical fixtures can't produce a valid plan

`6t_custom_example3` and `7t_custom_example1` are expected to fail downstream,
not because of anything in this repo's data, but because of open issues in the
tools that consume it:

- `6t_custom_example3`: the solver parks on a non-parking arrival track when it
  can't move into the yard immediately (`solver#13`).
- `7t_custom_example1`: the solver's cost function has no deadline for
  outStanding trains, so it produces a plan that overruns the scenario
  horizon for free, which then trips a diagnostic-quality bug in the
  evaluator's terminal-state handling rather than a clean failure
  (`solver#14`, `evaluator#6`).

Both were deferred deliberately rather than blocking 2.0.0. If you're running
the full pipeline and see these two fail, this is why.

**Update, 2026-09-12:** solver/evaluator `2.1.0` (shipped 2026-09-11) fixes
solver#13 and solver#14. Re-verified directly against `stable` today:

- `6t_custom_example3` now produces a **valid plan**. solver#13 is fully
  resolved — no longer a known limitation.
- `7t_custom_example1` is **still not valid**, but for a different, better
  reason: solver#14's fix means the solver no longer under-costs an
  outStanding overrun for free, and the evaluator no longer spins on it
  (evaluator#6 not triggered). Instead TORS now cleanly rejects the plan with
  a "departure mismatch" error — a real, still-untriaged defect. See
  [`docs/roadmap-2.0.0.md`](docs/roadmap-2.0.0.md) for the investigation and
  [`docs/scenario-feasibility.md`](docs/scenario-feasibility.md) for the
  fixture-level status.

### Fixture corpus and validation

`sweep_seeds.py --save` classifies a configuration's outcomes across a range
of seeds into `Location_*/fixtures/{feasible,infeasible,unresolved}/`.
`.github/workflows/validate-fixtures.yml` gates every push and PR on
`validate_json.py` against the JSON Schema `robust-rail-generator` exports
from its Pydantic models, itself gated on that schema being fresh relative to
the models — a stale schema doesn't fail validation, it validates against the
wrong contract and passes, which is the failure mode worth guarding against.

That gate is also why two further generator-side changes required edits
across the fixture corpus here, even though neither changes any tool's
runtime behavior. `reversalDuration` and `canDepartFromAnyTrack` are dropped
from the wire format entirely (traced as dead in generator, solver and
evaluator alike — see generator's `SCHEMA_CHANGELOG.md`); because `RailModel`
forbids extra fields, every fixture still carrying either key (all
`null`-valued) failed validation outright, so 71 files had the two keys
stripped. Separately, generated scenario JSON now ends with a trailing
newline; 60 checked-in fixture files that the pipeline doesn't regenerate got
the same newline appended by hand for consistency. Full verification
evidence for both is in `docs/roadmap-2.0.0-history.md`'s
[Release evidence](docs/roadmap-2.0.0-history.md#release-evidence) section.

### Pipeline scripts

`run_pipeline.py` drives `run_generator.py` → `run_solver.py` (or
`run_planner.py`, mutually exclusive with the solver — both write
`plans/plan_<name>.json`) → `run_evaluator.py`, or any subset via `--steps`.
`--version` now defaults to `2.0.0` rather than `legacy`: `legacy` stopped
working once Phase 1 moved these scripts to the unified format
unconditionally, so a default that reliably failed wasn't worth keeping.
`legacy` is still selectable explicitly for anyone doing a protobuf
comparison; retiring it outright is tracked as a follow-up.

### The planner is a live alternative, versioned separately

`run_planner.py` runs `ghcr.io/robust-rail-nl/planner`
(`planning-approach`), an alternative to the solver rather than an addition.
It's versioned independently (`0.1.0`, not `2.0.0`) — that number names the
three repos sharing the interchange format, and the planner's plans aren't
yet valid solutions (two known converter issues, tracked in
`docs/roadmap-2.0.0.md`), so it isn't part of this release train.

### Pre-unification leftovers cleaned up

Top-level `check_location_format.py`, which diffed `location.json` against
`location_solver.json`, is removed — the latter hasn't existed since Phase 1.
`Location_KleineBinckhorst/config_solver.yaml` lost its `LocationPath`/
`ScenarioPath`/`PlanPath` lines, which named that same retired file and were
never actually read (`run_solver.py` regenerates those three paths fresh into
a temp config on every run); the file's `Mode`/`DebugLevel`/`TabuSearch`/
`SimulatedAnnealing` settings are real, active solver-tuning parameters
(`run_solver.py:107`) and stay.
