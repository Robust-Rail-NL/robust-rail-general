# 2.0.0 release — open items

2.0.0 shipped 2026-08-24 (all four PRs sharing the interchange format merged;
see [`roadmap-2.0.0-history.md`](roadmap-2.0.0-history.md) for the full
verification log, resolved decisions, and what was done in each phase). This
file now holds only what's still open — kept short on the assumption most of
it either closes out or goes stale; check the dates before trusting anything
below.

---

## Known issues (open upstream, checked 2026-09-03; solver#13/#14 re-checked 2026-09-12 against shipped `stable`)

| issue | effect |
|---|---|
| solver#13 | Solver parks on non-parking arrival tracks when it cannot move into the yard immediately. Blocked `6t_custom_example3` under `stable`/`edge`. **Fixed and shipped** — solver PR #13 (`68aa9d4`, "Give a delayed Arrival a real duration instead of a trailing Wait") with a companion evaluator PR #13 (`6851675`) landed in solver/evaluator `2.1.0` (2026-09-11) and are now in `stable`. Re-verified directly against `stable` 2026-09-12 — see below. |
| solver#14 | outStanding trains have no deadline in the cost function, so plans over-run the scenario horizon for free. Produces the plan that trips evaluator#6. **Fixed and shipped** in solver `2.1.0` (2026-09-11), now in `stable`. Re-verified directly against `stable` 2026-09-12 — fixing it still isn't enough on its own to make `7t_custom_example1` valid, see below. |
| evaluator#6 | `EvaluatePlan` spins when the plan still has actions but the state is terminal, reporting the symptom rather than "plan extends past the horizon". Terminates via a safety valve; blocks nothing, but the diagnostic misleads. Still open (the spin bug itself isn't fixed) — but no longer triggered under `stable` now that solver#14 ships, since the overrun it was reacting to no longer happens. Confirmed 2026-09-12. |
| evaluator#1 | Invalid JSON for PB parsing fails quietly. On the legacy `--plan_type Evaluator` path only. |
| solver#17 | Solver and evaluator place a combined inStanding train's members at opposite ends of the track, so the solver routes a departing half out of the blocked end and calls the result feasible. Needs a decision on which convention is right, and probably a companion evaluator issue. |
| solver#18 | Solver ignores `standingIndex`, so the order of several standing units on one track is not the one the scenario asked for. **Fixed and shipped** in solver `2.1.0` too, but latent in this corpus regardless — every scenario here leaves the field null, so nothing to re-verify. The evaluator does honour it. |
| solver#19 | Question, not a defect: splitting a train in place costs no shunt move, and nothing prices the personnel it would need. |
| evaluator#17 | Once solver#14's overrun no longer masks it, TORS rejects `7t_custom_example1` with a different error: "departure mismatch" on `ShuntingUnit-4000`, whose declared departure time doesn't match its plan action's — the evaluator has no way to accept a late departure the solver already prices as `dd=1`, rather than treating it as unrecoverable. Reconfirmed present under shipped `stable` (2.1.0), 2026-09-12, and now filed — the sole remaining blocker for this fixture. |

None of #17, #18 or #19 blocks the pipeline. #17 needs a combined inStanding
train that gets split, which no fixture has; #18 needs a non-null
`standingIndex`, which no fixture has; #19 is a modelling question.

Both fixtures were named in `RELEASE_NOTES.md`'s 2.0.0 known-limitations
section as expected to fail under `stable`. As of solver/evaluator `2.1.0`
(shipped 2026-09-11) that's no longer true for both, though not in the same
way: `6t_custom_example3` now produces a valid plan under `stable` — solver#13
is fully resolved. `7t_custom_example1` needed more than solver#14 alone: the
free-overrun and the evaluator#6 spin are both gone, but the scenario still
fails, now on the untriaged departure-mismatch defect (see below).
`RELEASE_NOTES.md` has been updated to match.

### solver#14 verified fixed on edge, but `7t_custom_example1` still isn't valid

Checked 2026-09-03 by running the `edge`-channel solver against
`7t_custom_example1` in isolation (a scratch location dir with just this one
scenario, so the real fixture corpus wasn't touched), then the `stable`
evaluator against the resulting plan.

The overrun itself is gone: train 2401's last action previously ran
`01:20–01:35` against the `01:20` (T4800) horizon; on `edge` it finishes
`00:45–01:00`, comfortably inside it. The solver's own cost breakdown grew a
new `oo` counter (`cr=0, dd=1, da=0, tlv=0, sm=5, rd=498.80, cd=0, um=0,
oo=0`) that didn't exist before — matching the issue's suggested fix of
costing outStanding overruns as their own counter.

But TORS still calls the plan invalid, now for an unrelated reason that the
overrun previously masked (evaluator#6 never even triggers under `edge`,
since there's no more terminal-state mismatch to spin on): three "Trains's
departure mismatch with Action start/end time" errors, all at action time
`1830`, on `ShuntingUnit-4000` (the combined instanding pair 2801+2802,
scheduled departure `1500`) and the two outstanding units `2001`/`3001`
(recorded departure `0`). Whether this is a new regression from solver#14's
fix (its own writeup mentions plan serialization changed for `StandOut`
actions) or a pre-existing defect this scenario always had is not yet known —
needs its own investigation and, likely, its own issue before
`7t_custom_example1` can be called resolved.

### solver#13 verified fixed on local-edge, `6t_custom_example3` now valid

Checked 2026-09-04 by running the *entire* fixture corpus (both locations, all
12 scenarios — not just one scenario in isolation, unlike the solver#14 check
above) with `run_pipeline.py --version stable` and then `--version local`,
diffing evaluator verdicts and plan JSON between the two.

"Local" here means images built from each repo's `local-edge` branch: an ad
hoc branch, not part of the `stable`/`edge` channel model, that merges `edge`
plus every currently-open bugfix PR for that repo, so several not-yet-reviewed
fixes can be checked together before any of them lands on `edge`. Solver's
`local-edge` is `edge` + PR #13 (`68aa9d4`) + PR #14 (`4d5b592`, already
verified on `edge` separately, see above) + PR #30 (`c01e121`, a `SimulatedAnnealing`
config-key rename, unrelated to any fixture outcome). Evaluator's `local-edge`
is `edge` + the companion PR #13 fix (`6851675`) + `fix/silent-empty-protobuf-parse`
(evaluator#1-adjacent; not exercised by this corpus). Generator and planner have
no `local-edge` branch — their `local` images are plain rebuilds of `main`, and
produced byte-identical scenarios to `stable`, as expected.

`6t_custom_example3` flips from invalid to valid. Under `stable`/`edge` the
plan contained an explicit `Wait` action on gateway track 906a (`startTime:
900, endTime: 1110`), which the evaluator rejects outright since the gateway
forbids parking. Under `local-edge` that action is gone: the delayed Arrival
that used to end at `900` and hand off to the `Wait` now just runs to `1110`
itself, exactly matching the fix's description (give the Arrival a real
duration instead of a trailing `Wait`).

Verdict changed for exactly one scenario here, `6t_custom_example3` (invalid
→ valid). `7t_custom_example1`'s verdict is unchanged — still invalid — but
for a different *reason* than under plain `edge`: the same three "departure
mismatch" errors at action time `1830` as the 2026-09-03 check above, not the
evaluator#6 spin. All other scenarios' verdicts are unchanged from `stable`.

Plan content is a separate axis from verdict: 7 of the 12 fixture plans came
out byte-different from their `stable` counterparts regardless of verdict —
`10t_random_42s_distribution1`, `10t_random_42s_distribution2`,
`48t_custom_larger-example` and `30t_random_98s_test` (all four an unchanged
verdict, different plan bytes), plus `simple_service_location_4t_custom_late`
(same), and the two scenarios above with a verdict or failure-reason change.
This is consistent with solver#14's writeup noting a broader serialization
change around outStanding/`StandOut` actions, not just its cost-function fix.
The other 5 scenarios came out byte-identical:
`24t_custom_kleinebinckhorst_absolute_seconds`, `4t_random_1s_feasible_small`,
`2t_random_1s_marginal_length`, `8t_custom_example2`, and
`14t_random_1s_marginal_congestion`.

**Caveat:** `local-edge` is not a published or tagged image — it is a same-day
local build off a branch merging open, unreviewed PRs, one level more
provisional than `edge` itself. Read this as "the fix looks right and
introduces no regression across the fixture corpus," not as a substitute for
review or for the `edge`/`stable` promotion path. See
[`pipeline-integration-testing.md`](pipeline-integration-testing.md) for how
this kind of comparison is run in general.

### solver#13 and solver#14 re-verified fixed on `stable` (2.1.0), 2026-09-12

Both fixes shipped for real this time — solver/evaluator `2.1.0`, released
2026-09-11 — rather than the `local-edge`/`edge` builds the two checks above
were run against. Re-ran both scenarios in isolation (a scratch location dir,
fixture corpus untouched) against `ghcr.io/robust-rail-nl/hip:latest` and
`ghcr.io/robust-rail-nl/tors:latest`, both freshly pulled at `2.1.0`:

- `6t_custom_example3`: **valid**. Confirms solver#13's fix holds under
  `stable` proper, not just the `local-edge` build checked 2026-09-04.
- `7t_custom_example1`: the solver's own cost breakdown now honestly reports
  `dd=1` (previously a silent 0), and the evaluator no longer spins
  (evaluator#6 not triggered) — the free overrun really is gone. But the plan
  is still **not valid**: the same three "Trains's departure mismatch with
  Action start/end time" errors as the 2026-09-03/04 checks, all at action
  time `1830`, on `ShuntingUnit-4000` (declared departure `1500`) and
  outstanding units `2001`/`3001` (declared departure `0`). Tried seeds 1-4;
  all reproduce the identical `dd=1` outcome, so this isn't a seed-luck
  artifact of the default 40-iteration TabuSearch budget — it's the same
  untriaged defect as before, now confirmed present in the actual shipped
  release rather than only on unmerged branches.

  **2026-09-12, follow-up:** two of those three blocks (`2001`/`3001`) turned
  out to be an evaluator diagnostic bug, not a real mismatch involving those
  trains — they don't even share IDs with the action being evaluated.
  Root-caused and fixed in
  [robust-rail-evaluator#16](https://github.com/Robust-Rail-NL/robust-rail-evaluator/pull/16),
  merged into `main` the same day and now in `tors:edge` too. `stable`
  (`tors:latest`) is still `2.1.0` and will keep printing all three blocks
  until the next evaluator release ships; running against `--version edge`
  shows a single block for `ShuntingUnit-4000` only. Fixing the diagnostic
  doesn't touch the actual defect above — `4000`'s declared departure still
  doesn't match its plan action's time, and the evaluator still has no way
  to accept a late departure the solver has already priced as `dd=1` rather
  than treating it as unrecoverable — that part is still open, filed as
  [robust-rail-evaluator#17](https://github.com/Robust-Rail-NL/robust-rail-evaluator/issues/17).

---

## Open decisions

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

### Where the exported schemas should live — decided, not yet implemented

Tracked in [generator#14](https://github.com/Robust-Rail-NL/robust-rail-generator/issues/14).

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

The move is the whole `src/models/` directory — `location.py`, `scenario.py`,
`plan.py`, `scenario_config.py`, `utilities.py` — as one package, since `Plan`
embeds types from `location.py`/`scenario.py` and cannot move alone. Inside the
generator, only 3 files touch any of it (`check_config.py`,
`random_generator.py`, `scenario.py`), which become imports from the new
external package instead. `scripts/export_schema.py` moves here wholesale.

This **replaces** the branch-matching clone in `validate-fixtures.yml` rather
than just fixing it: once the models live here, the exported schema is direct
build output, not a copy of anything, so there is nothing left to go stale
against.

**Deliberately post-2.0.0.** Needs its own pass: packaging this repo as an
installable dependency (doesn't exist today), a pin/lockfile discipline in the
generator's build matching the Docker-tag pinning already in force, and a
decision on distribution mechanism (git dependency vs. a published package).

### Planner plans are not yet valid, and planner/solver output collides

`run_planner.py` works: the image plans `Location_SimpleService` into a plan
that validates against `schema_plan.json` with zero errors, and the evaluator
parses and executes it. The format contract holds end to end.

**The plans themselves are not valid solutions yet**, for two reasons that are
the planning-approach (now robust-rail-planner) team's, not the schema's:

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

## Open loose ends

Things I (LP) noticed and want to write down so we won't forget:

Generator:
- [generator#12](https://github.com/Robust-Rail-NL/robust-rail-generator/issues/12):
  `EvaluatorScenario` and `Scenario` represent the same concept twice —
  `ScenarioGenerator` accumulates into the flat, `Train`-based
  `EvaluatorScenario` shape, then `create_solver_format_scenario()` manually
  converts it, field by field, into the `Scenario` shape actually written to
  `scenario_*.json`. Kept in sync by hand, not by construction. Already
  tracked as "Next steps" item 6 in `unified-schema-design.md`; purely
  internal to the generator, doesn't touch the interchange schema.

Solver / HIP:
- The "merge coinciding Wait actions" commit (`e545f33`) seems to have partially
  lost its effectiveness: see differences between current and legacy (1.4.2) plan
  versions.
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
- ~~See if we can get the Python version of TORS to work?~~ Not worth it; already retired. The Python code in this repo was very outdated. The most recent version of the code lives in [AlgTUDelft/cTORS](https://github.com/AlgTUDelft/cTORS) / [ReubenJ/cTORS](https://github.com/ReubenJ/cTORS).
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

## Cleanup pending

- **Retire the `legacy` `--version` choice outright.** It stopped working once
  Phase 1 moved these scripts to the unified format unconditionally; kept
  around as a documented dead end rather than removed. Still an open call.

---

## In progress: `stable`/`edge` channels for the solver image

Started 2026-08-26/27, not part of the 2.0.0 record above. A `stable`/`edge`
channel model for the HIP solver image, so a fix can be published and run
before it's gone through PR review into `main`:

- Solver: new `edge` branch, `CONTRIBUTING.md` documenting the model, and
  `docker-push-edge.sh` (tags `<release>-edge+<date>.<short-sha>`, floats
  `hip:edge`).
- This repo: `run_*.py --version stable|edge` (renamed from `2.0.0`/
  `2.0.0-assert`; `edge` only has real meaning for the solver, the other
  tools resolve it to their `stable` image) and `docker_utils.ensure_pulled()`
  (originally `pull_flag()`, passing `--pull always` per `docker run`; changed
  2026-09-07 to a single `docker pull` up front instead) — so a floating tag
  like `:edge` is never served stale from a local cache.

Not written up anywhere longer-form than the git history itself; worth its
own doc if it grows more channels or more repos.

---

## Reference: decisions still in force

Not open items — these constrain anything built on the schema, so they're
kept here rather than in the history file for anyone starting new work.

| Decision | Resolution |
|---|---|
| `TrainUnitType.reversalDuration` | Computed from `backNormTime`/`backAdditionTime`; off the wire, derived locally |
| Type identity | `(typePrefix, carriages)`, not a combined `displayName` string. Consumers key on the pair |
| `TaskSpec.priority` | Renamed to `optional: bool` — TORS only ever used it as a 0/non-zero flag |
| `Resource` | `{ "kind": "trackPart"\|"facility"\|"staff", "id": <int> }`; `name` dropped; evaluator hard-errors on an unrecognised `kind` |
| `trainUnitTypes` | Stays on `Scenario`, referenced from `TrainUnit` |
| `Plan.trackParts` | Dropped — TORS loads infrastructure from `--path_location` |
| `schemaVersion` | One shared monotonic integer across `Location`, `Scenario` and `Plan`, starting at 1; all bump together |
| Version mismatch | **Warn and continue.** Never a hard reject. Each tool holds `EXPECTED_SCHEMA_VERSION` locally; this repo's `SCHEMA_CHANGELOG.md` records each bump |
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

See [`roadmap-2.0.0-history.md`](roadmap-2.0.0-history.md) for the branch
naming rationale, the rc-by-rc verification log, and the full "what was done"
table.
