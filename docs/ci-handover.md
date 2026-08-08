# CI (Phase 3c) — what was built, 2026-08-08

This started as a brief for a fresh session picking up the CI work. That work is
done; what follows is the outcome, kept because the reasoning behind a few of
the choices is not visible in the workflow files. The specification is Phase 3c
in `roadmap-2.0.0.md`.

## Where it lives

On `claude/2026-08-07-replay-fixes` in each of the four repos, validated through
draft PRs into the migration branches: solver #15, evaluator #5, generator #10,
this repo #7. Nothing was pushed to `noproto` or `pydantic`.

Note that in each local checkout the branch is *named* `noproto` / `pydantic`
but sits well ahead of the corresponding remote — the session work never landed
there. `git branch --show-current` is not enough to tell you what you are
looking at; compare against `origin/claude/2026-08-07-replay-fixes` too.

## What each repo got

| repo | workflow | check |
|---|---|---|
| `robust-rail-generator` | `python.yml` | `uv run pytest` (14); schema freshness |
| `robust-rail-solver` | `dotnet.yml` (existing, retargeted) | csharpier; build; smoke run; tests (35) |
| `robust-rail-evaluator` | `ctest.yml` (new) | cmake configure/build; `ctest` (7/7) |
| `scenario-planning-inputs` | `validate-fixtures.yml` (new) | schema freshness (gating); fixture validation (report-only) |

Triggers are push and pull_request on the stable branches plus the relevant
migration branch, and `workflow_dispatch`. There is deliberately no `claude/**`
wildcard: a session branch is validated by opening a PR, and the `pull_request`
event runs the workflow from the merge commit, so a workflow added in the PR
runs on its first push.

## Things that were not obvious

**The solver's workflow was already red, and the triggers were not the reason.**
It had never run on `noproto`, but PR #12 into `main` fired it on 2026-08-03 and
it failed in 29s. `Program.cs` had acquired an absolute
`/home/leon/Projects/...` prefix for its no-config default run, so that path
worked on one machine. Retargeting the triggers alone would have left it failing
on a step that has nothing to do with the migration.

**The evaluator's CI was more absent than it looked.** The only file under
`.github/` was an editor backup (`docker-image.yml~`), and `.github/` was not
tracked in git at all on `noproto`. The real workflow existed on a local
`main-leon` branch, was on no pushed branch, and built an image without running
a test.

**`EngineTest` and `CompatibilityTest` must not be given environment
variables.** They used to need `LOCATION_PATH`, `SCENARIO_PATH`, `PLAN_PATH` and
`RESULT_PATH`, and failed even when they were set. Both were rebuilt on
2026-08-07 to be self-contained; nothing reads those variables now, and setting
them in CI would only mislead the next person.

**The generator's schema export is the check everything else rests on.** The
schemas are generated from the Pydantic models, and the solver, the evaluator
and this repo all validate against them. A model edited without a re-export does
not produce a failure downstream — it produces a pass against the old contract.
So both the generator's workflow and this repo's re-export and diff them.

## Still open

- **The fixture validation here does not gate.** It reports 2 of 18 valid — the
  two `location.json` files. The drift is wider than this brief originally said:
  not just `Location_SimpleService`, but every scenario and every plan, for
  three separate reasons (train-unit ids are strings throughout; plans use
  `memberIDs` and `standingType` against a model that says `members` and forbids
  extras; `trainUnitIds` is always `null`). See Phase 3c in the roadmap. Settle
  those, then drop `continue-on-error` from
  `.github/workflows/validate-fixtures.yml`.
- **Where the schemas should be published.** This repo reads them from a
  generator checkout pinned to `pydantic`, which couples the repos. A release
  artifact (Phase 2) removes both that and the staleness risk.
- **Whether `--plan_type Evaluator` is still supported.** The cTORS-native plan
  path in `main.cpp` now has no test, and the pipeline always passes `Solver`.
- **`dotnet build` warnings-as-errors** for the solver, which currently builds
  with two nullable warnings in `Initial/SimpleHeuristic.cs`.
- Two open solver issues block two fixtures and are not CI's concern:
  Robust-Rail-NL/robust-rail-solver#13 and #14.
