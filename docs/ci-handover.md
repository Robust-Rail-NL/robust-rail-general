# Handover: setting up CI (Phase 3c)

Brief for a fresh session picking up the CI work. The specification is Phase 3c
in `roadmap-2.0.0.md`; this covers what a cold start would otherwise have to
rediscover, and the ways it could reasonably go wrong.

## Read this first: the work is on a branch

All of it lives on `claude/2026-08-07-replay-fixes` in each of the three code
repos, **not** on `noproto` / `pydantic`, which are unchanged on the remote.
Check the branch out before doing anything, or you will wire CI up against a
tree where the suites still fail.

| repo | base branch | session branch |
|---|---|---|
| `robust-rail-generator` | `pydantic` | *(no changes this session)* |
| `robust-rail-solver` | `noproto` | `claude/2026-08-07-replay-fixes` |
| `robust-rail-evaluator` | `noproto` | `claude/2026-08-07-replay-fixes` |
| `scenario-planning-inputs` | `pydantic` | `claude/2026-08-07-replay-fixes` |

## Current CI, which is less than it looks

| repo | what exists | reality |
|---|---|---|
| `robust-rail-generator` | nothing | no `.github` directory |
| `robust-rail-solver` | `.github/workflows/dotnet.yml` — csharpier, build, run, test | **triggers on `main` and `dev` only**, so it has never run on the migration branch |
| `robust-rail-evaluator` | `.github/workflows/docker-image.yml~` (an editor backup) | the real workflow exists only on a local `main-leon` branch, is on no pushed branch, and builds an image without running tests |
| `scenario-planning-inputs` | nothing | no `.github` directory |

So the solver's workflow is a good template that has simply never been pointed at
the right branches, and the evaluator effectively has no CI at all.

## Current state of the suites

All green as of 2026-08-08 on the session branch. Anything red is something you
changed.

| repo | command | result |
|---|---|---|
| generator | `python -m pytest -q` (in `.venv`) | 14 passed |
| solver | `dotnet test` | 35 passed |
| evaluator | `cmake --build build && (cd build && ctest)` | 7/7 passed |

The evaluator suite reaching 7/7 is new — `EngineTest` and `CompatibilityTest`
failed for years. Do not "fix" them again; see the traps below.

## Traps

**1. `EngineTest` and `CompatibilityTest` were just rebuilt.** They used to need
`LOCATION_PATH`, `SCENARIO_PATH`, `PLAN_PATH` and `RESULT_PATH` exported, and
failed even when they were set, because they pointed at a fixture using the
pre-unification field names. `CompatibilityTest` is now self-contained against
`data/Demo/hip_plan_evaluation_test`; `EngineTest` kept only its self-contained
case and its two environment-driven cases were deleted. **CI must not export
those variables** — nothing reads them any more.

**2. Do not pin a copy of the JSON schemas into this repo.** `validate_json.py`
here is a sketch that reads them from a generator checkout via `--schema-dir`,
which couples the repos; a pinned copy instead goes stale silently. Whatever the
source, CI must also check that the generator's committed `schema/*.json` still
matches `model_json_schema()`. Validating against a stale schema is worse than
not validating, because it reports success. The schemas were verified in sync on
2026-08-08.

**3. `validate_json.py` currently reports 2 of 19 files valid.** That is real
drift, not a broken script: train unit ids are strings in
`Location_SimpleService` where the schema says integer (the string-to-int
migration never reached it), and plans carry `null` where the schema says array.
Do not gate CI on it until that is triaged, or the first run is red for reasons
unrelated to CI.

**4. `scenario_config_*.json` has no schema and must keep accepting unknown
keys.** The generator's `check_config.py` is a list of presence checks that
rejects nothing it does not recognise, and the three configurations added this
session rely on that to carry their `intent` blocks. A strict config schema
would invalidate them.

**5. The solver's formatting check is load-bearing.** `dotnet csharpier check`
runs as a separate job, and a pre-commit hook reformats on commit. Keep both, and
expect CSharpier to rewrite files if you commit C# without running it.

## Suggested order

1. Fix the solver workflow's triggers so it runs on the migration branches, and
   confirm it passes there. Cheapest useful step, and it validates the template.
2. Give the evaluator a workflow: configure, build, `ctest`. It has none, and its
   suite is the one that had never run.
3. Add a generator workflow: `pytest`, plus the schema-freshness check.
4. Leave `scenario-planning-inputs` until trap 3 is triaged. Its check is JSON
   validation, which is currently red for pre-existing reasons.

## Things deliberately left open

- Whether `--plan_type Evaluator` (the cTORS-native plan path in `main.cpp`) is
  still supported. It now has no test, and the pipeline always passes `Solver`.
- Where the exported schemas should be published so that neither staleness nor
  repo coupling is required.
- Two open solver issues block two fixtures and are not CI's concern:
  Robust-Rail-NL/robust-rail-solver#13 and #14.
