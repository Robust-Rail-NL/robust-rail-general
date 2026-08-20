# Roadmap: 2.0.0 release of generator, HIP, and TORS

## Status

The unified interchange schema is frozen and implemented across all five repos.
The pipeline runs end-to-end on published images, all five repos have gating CI,
and the release evidence is recorded under [Release evidence](#release-evidence)
below.

**`2.0.0-rc.2` is cut and fully verified** as of 2026-08-20: tagged across all
five repos, plain and assert pipelines both re-run against published images,
every fixture plan byte-identical to the `rc.1` baseline (itself byte-identical
to beta.5) and every evaluation byte-identical between the plain and assert
passes. See [rc.2 — cut and verified](#rc2--cut-and-verified).

**`generator:2.0.0`, `hip:2.0.0` and `tors:2.0.0` are tagged** as of
2026-08-21 — re-tagged from the verified `rc.2` digests, confirmed identical
by digest, `:latest` moved alongside. All four PRs sharing the interchange
format are open and marked ready for review (not yet merged). See [Phase 4 —
Stable release](#phase-4--stable-release) for what's left.

Everything else outstanding is either a decision with no defect behind it, or a
known issue to name in the release notes. Three issues came out of the #11
investigation — solver#17, #18 and #19 — none of which blocks the pipeline; see
the table below.

> Condensed 2026-08-09, when the remaining work became small enough that the
> record of how we got here was crowding it out. Completed phases are summarised
> here as decisions-in-force plus a pointer; the full narrative — every commit,
> every measurement, every wrong turn — is in this file's git history. If you
> need to know *why* something is the way it is and the answer is not below,
> `git log -p docs/roadmap-2.0.0.md` has it.

---

## Branch naming

All five repos share one integration branch, **`release/2.0.0`**, merged into
each repo's stable branch and deleted when 2.0.0 ships. Renamed 2026-08-08 from
`pydantic` (generator, scenario-planning-inputs), `noproto` (solver, evaluator)
and `new_schemas` (planning-approach) — each named for an implementation detail
rather than the goal, and differing per repo.

The shared name is not only tidiness. `validate-fixtures.yml` reads the
generator's schemas from the branch of the same name, so that a coordinated
schema change is validated against its own schema rather than the base branch's.
That only works when the name matches everywhere.

References to the old names in git history are correct as written: that is where
the work happened at the time.

---

## rc.2 — cut and verified

All five repos tagged `2.0.0-rc.2`, one nameable candidate rather than
per-repo tags. `rc.2` carries the `standingIndex` schema change over `rc.1`
(`SCHEMA_CHANGELOG.md`'s "Unversioned — 2026-08-19" entry); both the plain
and assert pipelines have re-run against published `rc.2` images with output
byte-identical to `rc.1` throughout — see [Re-verified on
`hip:2.0.0-beta.5`](#re-verified-on-hip200-beta5), [Re-verified on
`2.0.0-rc.1`](#re-verified-on-200-rc1) and [Re-verified on
`2.0.0-rc.2`](#re-verified-on-200-rc2) for the full evidence chain. Nothing
left gating rc.2.

The remaining opens below are decisions with no defect behind them, and known
issues to name in the release notes — none block cutting `2.0.0` itself.

### What solver#11 turned out to be

The same `State` was departed twice, but not by the same task. `ComputeLocation`
treats a routing that ends on the track it started from as "nothing moved": the
next task takes over the previous task's `State` rather than departing and
re-arriving, which keeps the train's place in the occupation and is what makes
switching a task onto the from-track worth proposing at all.

That shortcut only works one-to-one. When such a routing is a **split**, every
one of its parts was given the same `State`, so each later removed the same deque
node and the second found it gone. `ParkingSwitchMove`/`ParkingSwapMove` create
the configuration by relocating a split's halves onto the routing's own
from-track.

The seed parity — 2/4/6/8/10/12 crash, odd ones pass — was the thread we expected
to pull hardest and turned out to be shallow: splits-in-place occur on exactly the
even seeds. Seed 1 runs 86,370 `ComputeModel` passes without one.

Two defects, fixed separately: the aliased `State`, and a serialisation crash it
uncovered (a routing's duration covers a split's decoupling as well as its
travel, so an in-place split emitted a Move action with an empty path). Then
modelled properly: the parts now take over the stretch the whole train held
rather than being departed and re-arrived at the end of the track, which had
understated the crossings they would later owe to get out.

`Tests/TestData/scenario_inplace_split.json` in the solver reproduces it
deterministically at seed 1 in under a second, replacing the thirty-second seed
sweep, and fails against both pre-fix states for the right reasons.

Full brief in solver#11's comments.

---

## Open — known issues to name in the release notes

| issue | effect |
|---|---|
| solver#13 | Solver parks on non-parking arrival tracks when it cannot move into the yard immediately. Blocks `6t_custom_example3`. |
| solver#14 | outStanding trains have no deadline in the cost function, so plans over-run the scenario horizon for free. Produces the plan that trips evaluator#6. |
| evaluator#6 | `EvaluatePlan` spins when the plan still has actions but the state is terminal, reporting the symptom rather than "plan extends past the horizon". Terminates via a safety valve; blocks nothing, but the diagnostic misleads. Blocks `7t_custom_example1`. |
| evaluator#1 | Invalid JSON for PB parsing fails quietly. On the legacy `--plan_type Evaluator` path only. |
| solver#17 | Solver and evaluator place a combined inStanding train's members at opposite ends of the track, so the solver routes a departing half out of the blocked end and calls the result feasible. Needs a decision on which convention is right, and probably a companion evaluator issue. |
| solver#18 | Solver ignores `standingIndex`, so the order of several standing units on one track is not the one the scenario asked for. Latent in this corpus — every scenario leaves the field null. The evaluator does honour it. |
| solver#19 | Question, not a defect: splitting a train in place costs no shunt move, and nothing prices the personnel it would need. |

solver#16 (`Deque.RemoveHead` throwing after a successful removal) was fixed in
`f99438c` and drops off this list.

None of #17, #18 or #19 blocks the pipeline. #17 needs a combined inStanding
train that gets split, which no fixture has; #18 needs a non-null
`standingIndex`, which no fixture has; #19 is a modelling question. They are here
because they were found under #11 and are easy to lose otherwise.

`6t_custom_example3` and `7t_custom_example1` therefore cannot produce a valid
plan. Both were deferred deliberately. Phase 4's "once integration tests pass"
should be read with that in mind — it is not literally true, and the release
notes should say which two fixtures are expected to fail and why.

---

## Open — decisions

### `--plan_type Evaluator`

Surveyed 2026-08-08 so this can be decided on evidence rather than on the name.

`main.cpp` takes `--plan_type Solver|Evaluator`. The two branches read different
plan formats, and the substantive difference is not the format: a `Run` is
**self-contained**, carrying its own scenario (`Plan.cpp:503`), while the Solver
path takes the scenario separately via `--path_scenario`.

The case for retiring it: `run_evaluator.py` always passes `Solver`, nothing in
the pipeline uses it, and it has no test — the only one that ever named it was
`EngineTest`'s "Plan test", deleted 2026-08-07, which had never passed.

It is also the sole remaining consumer of the legacy input shapes, and therefore
the reason several cleanups stopped short: `Plan.proto` still declares
`trainUnitIds` as `repeated string`, `Train.cpp` keeps its `"****"` placeholder
and `stoi()` guards, and `TrainUnitType::types` is still the string-keyed map
(`Train.h:15`) alongside the HIP path's `typesByPrefixAndCarriages`.

**Retiring it does not delete `Scenario.proto` and `Run.proto`**, which an
earlier draft claimed. The same formats are still *written*, from Python:
`RunResult::SerializeToFile` produces a `PBRun` and is bound in `pyTORS`
(`module.cpp:429`). The reader and that writer are two halves of one round trip.

So the decision is three:

1. Is the self-contained `Run` format wanted at all — as Python output, an
   archive format, a way to replay an evaluation?
2. If yes, does it need a *reader*, or is writing enough? Only the reader is
   `--plan_type Evaluator`; only the reader blocks the cleanups above.
3. If wanted in full, it needs a fixture and a test. It has neither, which is how
   it came to be forgotten.

Not a question CI can settle: nobody here has run that mode. Whoever knows why
the Python bindings exist should decide.

### Where the exported schemas should live — resolved, post-2.0.0

`validate-fixtures.yml` clones `robust-rail-generator` and reads `schema/` from
the branch of the same name. Vendoring a copy here would be worse — a stale
schema does not fail, it passes, having checked the wrong contract — so the
workflow also re-exports the schemas in that checkout and gates on them matching
what is committed there.

The branch guess has already produced one false reading: pinned to `pydantic`, a
run validated newly migrated fixtures against the pre-migration schema and
reported 2/18 for a tree really at 10/18, while the freshness gate stayed green
because that schema was perfectly consistent with the wrong models.

**Decided 2026-08-20, on a collaborator's suggestion: move `src/models/` out of
the generator and into this repo.** Not a schema-hosting tweak — the models
themselves relocate, and the generator becomes a consumer of a package published
from here rather than the other way round. The rationale is ownership, not
mechanics: the generator produces `location.json` and `scenario_*.json`, never
a plan, yet its models package currently owns `Plan` too; the configs
(`scenario_config_*.json`) already live under this repo's `Location_*/` and are
the one input in the pipeline that's hand-written rather than generated.

Checked before committing to it, since "the generator has nothing to do with
Plan" needed verifying rather than assuming:

- `Plan`/`Action` (`plan.py`) are imported by exactly one thing in the
  generator: `scripts/export_schema.py`. Nothing in the generator's own
  runtime — `scenario.py`, `random_generator.py`, `check_config.py`, `main.py`
  — touches them. But `Plan` embeds `Resource`/`TaskType` (from `location.py`)
  and `ShuntingUnit` (from `scenario.py`), so it cannot move alone without
  either duplicating those types or moving `location.py`/`scenario.py` with it.
  The interchange schema is one closed graph, not three independent files.
- `ScenarioConfig` (`scenario_config.py`) is the same story at the usage level
  — `export_schema.py` is its only importer; `check_config.py`'s actual
  validation never calls it, doing its own dict-based checks instead — but
  structurally simpler: it depends on nothing but the shared `RailModel` base
  in `utilities.py`, no cross-references into `location.py`/`scenario.py`. Its
  own docstring already says as much: "these are the `scenario_config_*.json`
  files under a location's `configurations/` directory in
  scenario-planning-inputs."

So the move is the whole `src/models/` directory — `location.py`, `scenario.py`,
`plan.py`, `scenario_config.py`, `utilities.py` — as one package. Inside the
generator, only 3 files touch any of it (`check_config.py`, `random_generator.py`,
`scenario.py`, a handful of import lines each), which become imports from the
new external package instead. `scripts/export_schema.py` moves here wholesale —
it has no generator-specific logic, it only calls `.model_json_schema()` on
models it no longer owns.

This **replaces** the branch-matching clone in `validate-fixtures.yml` rather
than just fixing it: once the models live here, the exported schema is direct
build output, not a copy of anything, so there is nothing left to go stale
against. It also resolves the "publish as a release artifact keyed by
`schemaVersion`" idea above — moot once there's no second copy to key.

**Deliberately post-2.0.0, not part of this release.** It changes ownership,
not schema content or runtime behaviour, so nothing about the 2.0.0 pipeline
depends on it landing first. Generator's PR (#11) is already out for review;
pulling `src/models/` out from under it now would reopen that diff. Needs its
own pass: packaging `scenario-planning-inputs` as an installable dependency
(doesn't exist today), a pin/lockfile discipline in the generator's build
matching the Docker-tag pinning already in force, and a decision on
distribution mechanism (git dependency vs. a published package).

### Renaming this repo to `robust-rail-general` — post-2.0.0

Under discussion. Checked what would actually break, across all four sibling
repos, before treating it as a git-settings change:

- **Load-bearing, would break outright:** `robust-rail-generator/src/main.py`
  and `src/example.py` default `--path` to a sibling directory literally named
  `scenario-planning-inputs`. `planning-approach/.github/workflows/schema.yml`
  clones this repo by that name, mounts it at `/siblings/scenario-planning-inputs`,
  and sets `RRN_INPUTS_DIR` to match — all three spots have to move together, or
  its CI breaks. `planning-approach/tests/test_plan_schema.py` makes the same
  sibling-directory assumption locally (`_sibling("scenario-planning-inputs",
  "RRN_INPUTS_DIR")`), overridable by the env var but not by default.
- **Present but not load-bearing:** `robust-rail-solver`'s
  `config_standard.yaml`/`config_simple_service.yaml` and
  `robust-rail-evaluator/data/Bugs/*/config_solver.yaml` hardcode
  `/workspace/scenario-planning-inputs/...` paths, but nothing in either
  repo's CI references them by name — manual/local-dev config, and already
  stale regardless (pre-unification `location_solver.json`/
  `scenario_solver.json` layout, removed in Phase 1).
- **Cosmetic only, safe to sweep separately:** READMEs, `SCHEMA_CHANGELOG.md`,
  `RELEASE_NOTES.md`, `unified-schema-design.md` and similar docs/comments
  across generator, evaluator and planning-approach. Not fully inventoried —
  `planning-approach/plan_visualizer/*.py` and
  `convert_to_pddl/**/convert.py` also matched a search for the name and
  weren't individually checked.
- **Not code:** GitHub redirects the old repo URL (web, clone, fetch/push)
  as long as nobody claims `scenario-planning-inputs` afterward, so PR links
  already shared keep working. Existing local clones should still get
  `git remote set-url origin <new-url>` explicitly rather than rely on that.

Sequence as a small coordinated PR in each affected repo (generator,
planning-approach at minimum) alongside the rename itself, not as a rider on
2.0.0.

### ~~`planning-approach/pipeline.py`~~ — resolved 2026-08-10

Deleted, along with `run.py`, `cli.py`, `evaluate.py` and `generate.py`, by
`new_pipeline_version`'s Docker-first restructure, which was merged into
`release/2.0.0` on 2026-08-10. The batch-driver role it played belongs to this
repo's `run_planner.py` / `run_evaluator.py` now, so the design question it
posed no longer needs answering.

Note what went with it and has **no** replacement: `src/local_search/solve.py`
and `src/plan/audit_discrete_plan.py`. Recoverable from
`git show 7c0346e:<path>`; recorded in `planning-approach/SCHEMA_STATUS.md`.

### The planner step is live, and its plans are not yet valid

`run_planner.py` can run: `ghcr.io/robust-rail-nl/planner` is built and pushed
by `planning-approach/docker-push.sh`, versioned from a `VERSION` file on that
repo's own line (0.1.0), deliberately not 2.0.0 — that number belongs to the
three repos sharing an interchange format.

**The format contract holds end to end.** The image plans
`Location_SimpleService` into a plan that validates against `schema_plan.json`
with zero errors, and the evaluator parses and executes it.

**The plans themselves are not valid solutions yet**, for two reasons that are
the planning-approach team's, not the schema's:

- The evaluator rejects the SimpleService plan with *"Facility 22 is not
  available from 1500 to 2000"*. No converter reads `timeWindow`, so the PDDL
  model cannot respect facility availability. Note the location declares no
  `timeWindow` on that facility at all, so the evaluator is applying a default
  from somewhere — worth establishing where before modelling it.
- `convert_to_tors` stops emitting actions partway through a plan: the trailing
  move/depart steps produce no `Exit`. Pre-existing and confirmed against
  `new_pipeline_version`'s own converter on its own fixture, so not schema
  drift. Held as a strict `xfail` in `test_main_plan_ends_with_an_exit`.

**Planner and solver are mutually exclusive.** Both write
`plans/plan_<suffix>.json`, and `run_evaluator.py` globs `plans/plan_*.json`, so
running both over one location yields one set of plans from whichever ran last
with nothing able to tell them apart. `run_pipeline.py` rejects the combination
rather than documenting it. Comparing planner and solver output on the same
scenario therefore needs a design — separate output directories, or a variant in
the filename that `run_evaluator.py` and the evaluation naming both understand.

---

## Open — loose ends

Things I (LP) noticed and want to write down so we won't forget:

Generator:
- [generator#12](https://github.com/Robust-Rail-NL/robust-rail-generator/issues/12):
  `EvaluatorScenario` and `Scenario` represent the same concept twice —
  `ScenarioGenerator` accumulates into the flat, `Train`-based
  `EvaluatorScenario` shape, then `create_solver_format_scenario()` manually
  converts it, field by field, into the `Scenario` shape actually written to
  `scenario_*.json`. Kept in sync by hand, not by construction. Already
  tracked as "Next steps" item 6 in `unified-schema-design.md`; purely
  internal to the generator, doesn't touch the interchange schema, doesn't
  gate 2.0.0.
- Clean up the generator's README.md: it has a TODO that should be dealt with
- Make sure the planner can also speak the new schema
- Figure out what to do with the regression-baseline files in the generator repo
  (just delete?). See also `src/generate-scenarios.sh`.
- Clean up the generator repo: automated formatting with pre-commit, Ruff etc.
- Decide what to do with `unified-schema-design.md`. At least remove in-progress
  bits?
- ~~Default scenario filename truncated the config name to its last
  underscore-token~~ — fixed on `generator@2d086f0`, shipped in `rc.1`
  (moved tag). `sweep_seeds.py`'s matching `base` formula updated alongside
  (`5911f1b`). `feasible_small`/`marginal_congestion`/`marginal_length` and
  the two `random_distribution*` fixtures were renamed to their un-truncated
  names as a result (`3fac5cb`).

Solver / HIP:
- The "merge coinciding Wait actions" commit (`e545f33`) seems to have partially
  lost its effectiveness: see differences between current and legacy (1.4.2) plan
  versions.
- Look through `git diff` with `main` / `dev`.
- `dotnet build` warnings-as-errors is a separate decision; the solver builds with
  two nullable warnings in `Initial/SimpleHeuristic.cs`.
- Rename `ServiceSiteScheduling.NoProto` (`Location.cs`, `Scenario.cs`,
  `Plan.cs`, `InterchangeSchema.cs`, `Utilities.cs` — the records that mirror
  the JSON interchange schema for deserialization). Named for what it isn't,
  a protobuf leftover from the migration. Suggest `Interchange`: matches the
  vocabulary this whole release already uses ("unified interchange schema"),
  and stays clearly distinct from the solver's own internal domain model
  (`Track`, `Train`, `State`, ...) elsewhere in `ServiceSiteScheduling` — bare
  `Model` would collide with that in meaning, not just in name.

Evaluator / TORS:
- Look through `git diff` with `main` / `dev`.
- See if we can get pyTORS to work? Probably not.
- **Do a focused session on TORS's own search mode.** TORS does not only replay
  and evaluate a plan; it can also generate one itself, and that looks to be what
  it was originally built for, with plan replay added later.

  This matters beyond curiosity. Nearly every evaluator bug found on 2026-08-07
  was a search-mode primitive behaving wrongly under replay, not a bug in its own
  right:
    - `legal_on_parking_track_rule` rejected a movement ending on a non-parking
      track. Harmless for the search, which emits step-by-step moves the rule
      exempts; fatal for replay, where every movement is a `MultiMove` and a
      departure's last movement lands on the gateway.
    - `Wait` runs until the next queued event. Correct for the search, which has
      no plan and re-decides at every event; wrong for replay, where it discards
      the duration the plan supplied.
    - `ArriveActionGenerator` hardcodes a zero duration, so a plan cannot express
      a train occupying the gateway while it waits for a route in (solver#13).
    - `out_correct_time_rule` demanded an exact departure time that an outStanding
      request (time 0) could never satisfy.

  The two modes share primitives whose contracts hold in only one of them. A
  survey of where else that is true would probably predict the next round of bugs
  rather than waiting to trip over them.

---

## Release evidence

### The `2.0.0-beta.3` run (2026-08-09)

The first end-to-end run against **published** images since 2026-08-02, and the
first at all since every id became an int and three fields were renamed and four
deleted. Everything in between was checked by schema validation and unit tests,
which establish that the files are well formed and that each tool parses them
alone — not that the three agree at runtime.

11 scenarios: the 8 canonical plus the three configurations added 2026-08-07.
Generator 11/11, solver 11/11, evaluator 8/11 exit-0. Whole pipeline: 2m20s.

| Scenario | Verdict |
|---|---|
| `4t_random_1s_small` | **valid** |
| `2t_random_1s_length` | **valid** |
| `8t_custom_example2` | **valid** — was rejected on 2026-08-02 |
| `10t_random_42s_distribution1` | infeasible: arrival train 270.62 m > track 15's 255 m |
| `10t_random_42s_distribution2` | infeasible: departure train 270.62 m > track 15's 255 m |
| `48t_custom_larger-example` | infeasible: arrival train 1006 324.12 m > 255 m |
| `14t_random_1s_congestion` | not valid: adding SU-12 to 906b exceeds 255 m |
| `6t_custom_example3` | not valid: parking not allowed on 906a (solver#13) |
| `7t_custom_example1` | not valid: no-progress guard at T4800 (solver#14 + evaluator#6) |
| `30t_random_98s_test` | not valid |
| `simple_service_4t_custom_late` | not valid |

**`example2` moved from rejected to valid** — the clearest evidence the
2026-08-07 replay fixes were worth making.

**The assert pass agrees.** Re-evaluating the same plans with
`--version 2.0.0-assert`, which differs from `2.0.0` in exactly one image,
gave identical verdicts on all 11 and 26 of 27 byte-identical output files; the
twenty-seventh differs only in `docker pull` chatter. No assertion fired.

The second pass must be `--steps evaluator`: re-solving would produce its own
plans and the diff would compare two unrelated things.

**The solver is deterministic run-to-run.** Four consecutive runs produced
byte-identical plans for all 11 scenarios. A wall-clock-bounded local search
would not normally be reproducible; it is here because `StopWhenFeasible: true`
means these searches terminate on a condition and none comes near the 3600 s
budget. That guarantee is conditional — it would not hold for a scenario hard
enough to exhaust the budget.

**Regenerated scenarios are semantically identical to the committed ones**, all
differences being key order (`id` moved to the front) with equal parsed content.

### Re-verified on `hip:2.0.0-beta.4`

The solver moved to beta.4 for `641e380`. Re-ran the whole pipeline: all eleven
plans byte-identical, all eleven verdicts unchanged. That commit is inert on
healthy paths.

The generator and evaluator stay at beta.3, which is correct rather than an
oversight — neither repo's compiled source changed after its beta.3 tag. Versions
here are per-repo, not a release train, and the `--version` key names a pipeline
configuration rather than a shared version number.

`beta.3` was deliberately **not** re-tagged onto the newer commit. Those images
produced the evidence above, and moving a published tag would make it
unreproducible.

**The warning that used to be here has been settled by measurement, in the
cheap direction.** It said a solver#11 fix would change what the parking model
computes, so plans could legitimately differ and the fixtures might need
regenerating rather than re-confirming.

Measured over all 10 KleineBinckhorst scenarios at seeds 1-6, solver and
evaluator, before and after the fix: **57 of 57 plans byte-identical, no verdict
changed.** The only difference is that the three runs that previously crashed now
produce a plan. The fix does change the parking model, but only on a
configuration — a split that stays on its own track — that healthy runs never
reach, which is the same reason the crash only ever appeared on even seeds.

So re-verification was expected to be a formality, with two caveats: the sweep
used a local assertions build at `MaxDuration: 15` rather than the published
image at the pipeline's `3600`, and it covered KleineBinckhorst only. Both are
now closed by the beta.5 run below, which used the published image at the full
budget and included SimpleService.

### Re-verified on `hip:2.0.0-beta.5`

The solver moved to beta.5 for the solver#11 fix (`6317d8e`, `82c825f`,
`87a48c9`, `5a4a7f8`, `2bd3bf2`) and `f99438c` (solver#16). Re-ran the whole
pipeline on 2026-08-10, generator through evaluator, 2m05s:

- Generator 11/11, solver 11/11, evaluator 8/11 exit-0 — the same counts as
  beta.3 and beta.4.
- **All 11 plans byte-identical** to the beta.4 run, and **all 11 evaluation
  outputs byte-identical** too. Not just the same verdicts: the same bytes.
- Regenerated scenarios again differ from the committed ones only in key order,
  parsing equal on all 8 that the generator rewrites.

This is the outcome the seed sweep predicted, now at the pipeline's own budget
and covering both locations. The fix changes the parking model only on a
configuration healthy runs never reach.

The generator and evaluator stay at beta.3 for the same per-repo reason as
before; neither repo's source has changed since.

Not yet covered: the assert pass. `hip:2.0.0-beta.5-assert` was still building
when this ran, so the run above is the plain image only. No assertion has been
exercised against the fix outside the solver's own tests.

### Re-verified on `2.0.0-rc.1`

All five repos tagged `2.0.0-rc.1`, this repo's `--version` selectors repointed
(`7989c59`), and the pipeline re-run on 2026-08-11 against the published
non-assert images (`generator:2.0.0-rc.1`, `hip:2.0.0-rc.1`,
`tors:2.0.0-rc.1`), 2m06s:

- Same counts as every prior run: generator 11/11, solver 11/11, evaluator
  8/11 exit-0.
- **Every plan in the committed fixture set is byte-identical** to the
  beta.5 run. The three non-fixture scenarios added 2026-08-07
  (`14t_random_1s_congestion`, `2t_random_1s_length`, `4t_random_1s_small`)
  aren't in git to diff against, but their solver/evaluator exit codes match.
- The one stderr size change (`distribution1`, 2 lines → 32) is `docker pull`
  chatter from the first pull of the new tag, not a content difference — the
  same kind of noise the beta.3 evidence already called out.

`hip:2.0.0-rc.1-assert` is published; `tors:2.0.0-rc.1-assert` is still
building, so the assert pass is the one thing this run does not cover.

**Assert pass, 2026-08-11.** `tors:2.0.0-rc.1-assert` published; re-ran
`--version 2.0.0-assert --steps evaluator` against the plans already on disk
(re-solving would produce different plans and the diff would compare two
unrelated things). All 11 evaluation outputs byte-identical to the plain
`tors:2.0.0-rc.1` pass — same 8/11 exit-0 pattern, no assertion fired.

**The rc.1 gate is now fully closed**: every image is published, the pipeline
has run against all of them, plain and assert agree, and every fixture plan
matches beta.5. (Superseded by `rc.2`, above — this entry stays as the record
of how `rc.1` itself was closed.)

### Re-verified on `2.0.0-rc.2`

`rc.2` across generator, hip and tors carries the `standingIndex:
Optional[float] -> Optional[NonNegativeInt]` change (see
`SCHEMA_CHANGELOG.md`'s "Unversioned — 2026-08-19" entry) and the new
standing-order consistency check. Re-verified in two steps as each image
landed:

- **Generator + solver**, once `hip:2.0.0-rc.2` was published: full
  `--steps generator,solver` run, all 11 canonical scenario/plan pairs
  byte-identical to the committed baseline. Expected — every fixture already
  has `standingIndex: null`, so the type narrowing is a no-op on the wire, and
  the solver's own change (`?? 0.0` → `?? 0` in `ProblemInstance.cs`) doesn't
  observably affect output either.
- **Evaluator**, once `tors:2.0.0-rc.2` was published: ran against the same
  plans. `docker inspect` showed `rc.1` and `rc.2` are genuinely different
  image digests (a real rebuild, not a re-tag), so this wasn't assumed safe —
  re-ran the same plans against `tors:2.0.0-rc.1` for comparison and diffed
  all 11 canonical `.txt` outputs: byte-identical. Confirms the changelog's
  claim that the evaluator needed no code change, in the actual output, not
  just the source diff.

**Assert pass, 2026-08-20.** `tors:2.0.0-rc.2-assert` published; re-ran the
same plans against it. All 11 canonical evaluations byte-identical to the
plain `rc.2` pass — no assertion fired. `rc.2` is now verified as fully as
`rc.1` was: generator, solver and evaluator all checked, plain and assert.

### What these runs do not cover

- x86-64 only. arm64 is covered at the unit-test level (evaluator and solver CI
  matrices, 2026-08-09) but the pipeline has never run there. A cross-arch
  comparison would not be meaningful anyway — different machine, and the
  determinism guarantee is conditional on not exhausting the time budget.
- Only `Seed: 1`. That is why solver#11 never fired here even before the fix:
  the triggering configuration does not arise on that seed at all. The pipeline
  exercises one path through the search per scenario, not the search's range —
  the seed sweep in the solver repo is what covers that.

---

## Phase 4 — Stable release

PRs open in all four repos sharing the interchange format (`planning-approach`
deliberately excluded — not ready), `release/2.0.0` into each stable branch:
[generator#11](https://github.com/Robust-Rail-NL/robust-rail-generator/pull/11),
[solver#20](https://github.com/Robust-Rail-NL/robust-rail-solver/pull/20),
[evaluator#7](https://github.com/Robust-Rail-NL/robust-rail-evaluator/pull/7),
[this repo#8](https://github.com/Robust-Rail-NL/scenario-planning-inputs/pull/8).
Opened as drafts, not for line-by-line review of a months-long migration diff —
a coordination point and a CI run against the real merge target.

- ~~Write the release notes.~~ Done 2026-08-20: `RELEASE_NOTES.md` now exists
  in all four repos. This one names solver#13, solver#14 and evaluator#6, and
  the two fixtures they permanently block (`6t_custom_example3`,
  `7t_custom_example1`) — otherwise "integration tests pass" reads as more
  true than it is.
- ~~Update this repo's `README.md`.~~ Done 2026-08-20: rewritten for the
  single-file pipeline, historical two-file framing dropped rather than
  footnoted.
- `--version` now defaults to `2.0.0` instead of `legacy` (2026-08-20) —
  `legacy` stopped working once Phase 1 moved these scripts to the unified
  format unconditionally, so a default that reliably failed wasn't worth
  keeping. Retiring the `legacy` choice outright is still open. (The
  `*-protobuf`/`*-pydantic` comparison directories were never committed —
  local scratch output only, deleted 2026-08-10. The comparison they produced
  is recorded in this file's git history, not in the files themselves.)
- ~~Mark the four PRs ready~~ Done 2026-08-21: all four are `draft=false`,
  `state=OPEN`. **Not merged yet** — deliberately separate steps; merge order
  still matters (generator's `main` before this repo's, see [Branch
  naming](#branch-naming)), and this repo's PR has a known conflict with
  `main` on `CLAUDE.md` to resolve first (see the PR body). solver#20 now
  targets `main` directly rather than `dev` (retargeted 2026-08-21, before
  any review — see `CLAUDE.md`): `release/2.0.0` already contains `dev`'s
  full history, so this one merge covers both without a separate promotion.
  `dev` itself is being updated by hand, outside this release's merge
  sequence. Still open: merge all four, then delete `release/2.0.0` in each.
- ~~Tag `generator:2.0.0`, `hip:2.0.0`, `tors:2.0.0` by re-tagging the
  existing `rc.2` digests~~ Done 2026-08-21, confirmed by digest: `2.0.0` and
  `2.0.0-rc.2` are byte-identical images in all three repos, not rebuilds.
  `:latest` moved to `2.0.0` in all three as well, also confirmed by digest —
  first stable tag of the release, per the "hold `latest` for the stable tag,
  not the rc/beta line" decision.

---

## Settled — decisions still in force

These constrain anything built on the schema, so they outlive the phases that
produced them.

| Decision | Resolution |
|---|---|
| `TrainUnitType.reversalDuration` | Computed from `backNormTime`/`backAdditionTime`; off the wire, derived locally |
| Type identity | `(typePrefix, carriages)`, not a combined `displayName` string. Consumers key on the pair |
| `TaskSpec.priority` | Renamed to `optional: bool` — TORS only ever used it as a 0/non-zero flag |
| `Resource` | `{ "kind": "trackPart"\|"facility"\|"staff", "id": <int> }`; `name` dropped; evaluator hard-errors on an unrecognised `kind` |
| `trainUnitTypes` | Stays on `Scenario`, referenced from `TrainUnit` |
| `Plan.trackParts` | Dropped — TORS loads infrastructure from `--path_location` |
| `schemaVersion` | One shared monotonic integer across `Location`, `Scenario` and `Plan`, starting at 1; all bump together |
| Version mismatch | **Warn and continue.** Never a hard reject. Each tool holds `EXPECTED_SCHEMA_VERSION` locally; `SCHEMA_CHANGELOG.md` in the generator records each bump |
| Every id | An `int`, including the composite ones |
| Arrays of IDs | Always end in `IDs` — `memberIDs`, `parentIDs`, `relatedTrackPartIDs`. `IncomingTrain.members` and `Train.members` keep their names because they really do embed their units |
| Retired proto fields | `reserved`, never freed, so a later field cannot inherit a number and meet an old message carrying the old meaning |

**Two traps worth keeping.**

*The proto names lie about which file is live.* Each of the three inputs uses a
different family, and the family called legacy is simultaneously the engine's
internal representation:

| proto | what it actually is |
|---|---|
| `Location.proto` | **live input** — `location.json` parses into `proto_tors::Location`, *not* anything HIP |
| `HIP_Scenario.proto` | **live input** — `scenario.json` |
| `HIP_Plan.proto` | **live input** — `plan.json` under `--plan_type Solver` |
| `HIP_Common.proto` | **live** — shared by the two above |
| `Plan.proto`, `PartialOrderSchedule.proto` | engine internal representation, *and* an input under `--plan_type Evaluator` |
| `Scenario.proto`, `Run.proto` | reachable **only** under `--plan_type Evaluator` |

Anyone reasoning from the names picks the wrong file — which happened during
Phase 3e, when a rename went into `HIP_Location.proto` and the compiler pointed
out the live path reads `proto_tors::Facility`.

*Protobuf cannot express an absent list.* `trainUnitIds` was documented as "if
not specified, all train units are involved". That contract was never
expressible: `repeated` fields carry no presence information, so absent, `null`
and `[]` all arrive as the same empty field. Anything reintroducing an optional
list needs a deliberate design for presence, not just the field back.

---

## Settled — what was done

Full detail in git history; commit ranges given where they help.

| Phase | Outcome |
|---|---|
| 0 — Design decisions | All eight resolved; results in the table above |
| 1a — `schemaVersion` | Implemented in all three tools plus fixtures |
| 1 — Scenario unification | One `scenario_*.json` per case in HIP field names; `scenario_solver_*.json` retired; `location_unified.json` → `location.json`. Solver retired `DeepLook`, `Converter.cs` and every protobuf-shaped class; evaluator migrated its read path and simplified the service-task rules |
| 2 — Generator cleanup | protobuf dependency dropped; `typePrefix`/`carriages` identity; `optional: bool`; PascalCase enums; JSON Schema exported |
| 3 — Integration testing | Parity established against the protobuf baseline (6/8 byte-identical, 2/8 same verdict); three evaluator crash bugs found and fixed along the way |
| 3c — CI | All five repos gate on push and PR. Generator `pytest` + schema freshness; solver `csharpier`, build, smoke run, 35 tests; evaluator `ctest` 7/7; this repo's fixture validation; planning-approach schema tests. arm64 matrices added 2026-08-09 for the two compiled repos |
| 3d — Every id an int | Across all three repos and every fixture. Removed four `stoi()` calls from cTORS and fixed a latent sort bug where `ShuntingUnit.Id` sorted unit 10 before unit 2 |
| 3e — Naming convention | `*IDs` everywhere; `Action.trainUnitIds`, `ShuntingUnit.standingType` and `Plan.trackParts` deleted as written-by-nobody and read-by-nobody; the `Park` task type turned out unreachable |
| 3f — Proto layout | `HIP_Location.proto` held four unreachable messages; removed and renamed to `HIP_Common.proto`. The rest is blocked on the `--plan_type Evaluator` decision |
| 3g — planning-approach | Converter now writes plans the schema accepts (269 validation errors to 0); `standingType` translated to the `StandIn`/`StandOut` task types rather than deleted; first tests and CI added. `pipeline.py` still open, above |
| Fixture corpus | `sweep_seeds.py --save` writes a classified corpus under `Location_*/fixtures/{feasible,infeasible,unresolved}/`; all of it validated by `validate_json.py`, which CI gates on |
