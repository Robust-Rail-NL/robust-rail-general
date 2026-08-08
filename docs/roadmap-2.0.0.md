# Roadmap: 2.0.0 release of generator, HIP, and TORS

## Context

The pydantic pipeline (generator, hip, tors) runs end-to-end on a single `location.json`.
Protobuf-vs-pydantic comparison results are recorded directly in Phase 3 below (the
standalone `docs/protobuf-pydantic-comparison.md` was retired once that became the
single source of truth for parity results — see git history if the old alpha-era
category-by-category diff catalog is ever needed). The remaining work before stable
2.0.0 releases falls into four areas:

1. **Scenario unification** — the generator currently emits two files per scenario:
   `scenario_*.json` (non-HIP field names, for the evaluator) and `scenario_solver_*.json`
   (HIP field names, for the solver). The goal is one file, one schema, consumed by both.
2. **Resolve open design questions** before freezing the schema.
3. **Coordinated breaking changes** in HIP (C#) and TORS (C++) to match the unified schema.
4. **Generator cleanup** — drop the protobuf dependency; finalise `displayName` and `priority`.

The design source of truth is `robust-rail-generator/unified-schema-design.md`.
The integration test harness is this repo (`scenario-planning-inputs`).

---

## Phase 0 — Decisions required before code changes

These are judgment calls that block schema work. Resolve them in the design doc first.

| # | Question | Where it matters |
|---|---|---|
| 0a | ~~Is `TrainUnitType.reversalDuration` computed from `backNormTime`/`backAdditionTime`, or a separate concept?~~ | **Confirmed computed** — drop from wire format; HIP C# derives it locally |
| 0b | ~~Confirm `displayName` cleanup: `"SLT"` + `carriages: 4` instead of `"SLT4"`~~ | **Confirmed** — `displayName` is type family only; `carriages` is separate; consumers key on `(displayName, carriages)` pair |
| 0c | ~~`TaskSpec.priority`: confirm it can be dropped everywhere~~ | **Resolved: rename to `optional: bool`** — TORS uses it as a binary 0/non-zero flag only; HIP drops it entirely |
| 0d | ~~`Resource` discriminator: keep "exactly one of three nullables" or introduce an explicit `kind` field?~~ | **Resolved: `{ "kind": "trackPart"\|"facility"\|"staff", "id": <int> }`** — part of schemaVersion 1; `name` field dropped; evaluator hard-errors on unrecognised `kind` |
| 0e | ~~Does `trainUnitTypes` stay on `Scenario`, referenced by name from `TrainUnit`?~~ | **Confirmed** — already the case in pydantic output |
| 0f | ~~`Plan`: same schema file as Scenario/Location, or separate? And remove `Plan.trackParts`?~~ | **Resolved** — `plan.py` is already separate; TORS never reads `trackParts` (uses `--path_location`); drop field from schema and stop emitting it in HIP |
| 0g | ~~Schema versioning: add `schemaVersion` to `Location`, `Scenario`, and `Plan` top level?~~ | **Decided** — see Phase 1a below |
| 0h | ~~Forward-compatibility policy: `extra="forbid"` or `extra="ignore"` for new optional fields?~~ | **Decided: warn-and-continue** — see Phase 1a below |

---

## Phase 1a — `schemaVersion` field ✓ COMPLETE

### Decisions

- **Format:** independent monotonic integer, starting at `1` for the 2.0.0 release.
  Increments only on breaking schema changes, decoupled from tool release versions.
- **Scope:** one shared interchange version across `Location`, `Scenario`, and `Plan`.
  All three carry the same value; all three bump together on a breaking change.
- **Mismatch behaviour:** warn-and-continue. A missing or unexpected `schemaVersion`
  produces a logged warning; parsing proceeds regardless. No hard reject.
- **Constant:** each tool defines `EXPECTED_SCHEMA_VERSION = 1` locally. All three are
  updated together as part of a coordinated release when the version increments.
- **Changelog:** `SCHEMA_CHANGELOG.md` in `robust-rail-generator` records what changed
  at each version.

### Implementation per repo

**`robust-rail-generator` (Python/Pydantic)**
- Add `schema_version: int = 1` to `Location`, `Scenario`, and `Plan` Pydantic models
  (wire name `schemaVersion` via `alias` or `model_config`)
- Generator emits `schemaVersion: 1` in output `scenario_*.json`
- Generator warns on read if `location_unified.json` has a missing or unexpected value
- Create `SCHEMA_CHANGELOG.md`

**`robust-rail-solver` (HIP, C#)**
- Add `SchemaVersion` property (JSON: `schemaVersion`) to `Location`, `Scenario`, `Plan` records
- On read (`Location`, `Scenario`): warn if missing or `!= EXPECTED_SCHEMA_VERSION`
- On write (`Plan`): emit `schemaVersion: EXPECTED_SCHEMA_VERSION`

**`robust-rail-evaluator` (TORS, C++)**
- Parse `schemaVersion` from `Location`, `Scenario`, and `Plan` JSON
- On read: warn if missing or `!= EXPECTED_SCHEMA_VERSION`
- No write path needed (TORS is a pure consumer)

**`scenario-planning-inputs` (this repo)**
- Add `"schemaVersion": 1` to `location_unified.json` in each `Location_*` directory
- No script changes needed

---

## Phase 1 — Scenario unification

**Goal:** one `scenario_<X>.json` per case, consumed by both the solver and the evaluator.

### Current situation

The two files differ in the field names used for `IncomingTrain` and `TrainRequest`:

| Concept | `scenario_*.json` (evaluator, non-HIP) | `scenario_solver_*.json` (HIP) |
|---|---|---|
| Entry track | `sideTrackPart` | `entryTrackPart` |
| First parking track | `parkingTrackPart` | `firstParkingTrackPart` |
| Arrival time | `time` (overloaded) | `arrival` |
| Departure time | (absent) | `departure` |
| Can depart from any track | `canDepartFromAnyTrack` | (absent) |
| Minimum duration | `minimumDuration` | (absent) |
| `outStanding` member list | `members` (IncomingTrain shape) | `trainUnits` (TrainRequest shape) |
| `outStanding` parking track | `parkingTrackPart` | `lastParkingTrackPart` |
| `outStanding` exit track | `sideTrackPart` | `leaveTrackPart` |

Per `unified-schema-design.md`, the unified model adopts the HIP field names.
`canDepartFromAnyTrack` and `minimumDuration` need explicit decisions (keep on
`TrainRequest`, or drop).

### Changes by repo

**`robust-rail-generator`** — Phase 1 ✓ COMPLETE, Phase 2 ✓ COMPLETE

Completed (branch `pydantic`):
- ✓ Emits one unified `scenario_*.json` (HIP field names); `scenario_solver_*.json` retired
- ✓ `scenario-planning-inputs/run_solver.py` updated to read `scenario_*.json`
- ✓ `location_unified.json` renamed to `location.json`
- ✓ Phase 2 cleanup (commits `d65d1ec`–`b54080c`): protobuf dependency dropped
  (`bf99964`), `typePrefix`/`carriages` identity + `TaskSpec.optional` (`0fda86f`),
  JSON Schema exported (`fd553e8`), pytest suite added (`c9e2a84`)
- ✓ Bumped to `generator:2.0.0-beta.1` (`b54080c`)

**`robust-rail-solver` (HIP, C#)** — Phase 1 ✓ COMPLETE

Completed (commits `96ad4ce`–`6ca108b` on `noproto`):
- ✓ Retired legacy `DeepLook` mode, `Converter.cs`, and all protobuf-shaped classes
- ✓ `ShuntingUnit.Members` (embedded) → `MemberIDs` (string list); `Members` dropped
- ✓ `PredefinedTaskType` extended: `Walking`, `Break`, `NonService`, `StandIn`, `StandOut` added
- ✓ `TaskSpec.Priority` dropped
- ✓ `Resource` switched to `{ kind, id }` discriminator
- ✓ `schemaVersion` added to `Location`, `Scenario`, `Plan`
- ✓ JSON numbers unquoted (dropped `WriteAsString` protobuf holdover)
- ✓ `IncomingTrain.StandingIndex` already present
- ✓ Enum serialization fixed to PascalCase (`c05bbf4`) — `JsonStringEnumConverter()`
  with no naming policy, replacing `JsonNamingPolicy.CamelCase` in both
  `ProblemInstance.cs` and `Extensions.cs`
- ✓ `TrainUnitType`/`TrainUnit`/`IncomingTrainUnit`: `TypePrefix`+`Carriages` identity
  (`0c03b79`) — `DisplayName`/`TypeDisplayName` dropped; `Equals`/`GetHashCode` and
  `traintypemap` all key on `(TypePrefix, Carriages)`
- ✓ Fixed action-sort collision (Move sorting after Exit) and a `NullReferenceException`
  logging optional InStanding/OutStanding (`dc607cd`, `0015e73`)
- ✓ Bumped to `hip:2.0.0-beta.1` (`1d695b7`) — **tag already cut**
- ✓ `TestData/setting_A` fixtures refreshed with real unified-format data (`6ca108b`)

**`robust-rail-evaluator` (TORS, C++)** — Phase 1 ✓ COMPLETE (tag pending)

Completed (commits `989806c`–`dbebb71` on `noproto`):
- ✓ `HIP_Scenario`/`HIP_Location` protos extended to the unified schema shape
- ✓ Scenario read path migrated to the unified (HIP) schema; `Task::priority` (int)
  → `Task::optional` (bool); `mandatory_service_task_rule`/`optional_service_task_rule`
  simplified accordingly (`033076e`)
- ✓ `PredefinedTaskType`: dropped `allow_alias`/lowercase names, PascalCase only (`4494db2`)
- ✓ Fixed `Scenario.in`/`out`/`inStanding`/`outStanding` wire shape mismatch (`5ce2ba0`,
  documented in `910b82d`)
- ✓ `TrainUnitType`/`TrainUnit` identity: HIP read path keyed on `(typePrefix, carriages)`
  (`fb6d3b3`); fixed carriage-blind type matching in `CheckScenarioCorrectness`/`ShuntingUnit`
  (`220215d`)
- ✓ `schemaVersion` parsed from `Location`, `Scenario`, `Plan` (warn-and-continue)
- No `Plan.trackParts` work needed — TORS already ignores this field entirely; all
  infrastructure is loaded from `--path_location` via `LocationEngine`
- Env-var-gated EngineTest/CompatibilityTest cases documented as deferred (`dbebb71`)

All three repos have finished Phase 1 and Phase 2, and all three are tagged and
released as Docker images to ghcr.io:
- ✓ `generator:2.0.0-beta.1`
- ✓ `hip:2.0.0-beta.1`
- ✓ `tors:2.0.0-beta.1`

Phase 3 (integration testing, below) is now unblocked.

---

## Phase 2 — Generator schema cleanup ✓ COMPLETE

These were generator-internal changes, unblocked once Phase 0 decisions were resolved.
See the generator Phase 1/2 summary above (commits `d65d1ec`–`b54080c`) for what landed:

- ✓ Drop protobuf dependency (`py_protobuf/`, `google-protobuf` package)
- ✓ Implement `typePrefix`/`carriages` identity in Pydantic models (rename
  `display_name` → `type_prefix` on `TrainUnitType`; add `type_prefix`/`carriages`
  to `TrainUnit`; `typeDisplayName()` derived; both known key bugs in
  `add_custom_train_unit_types`/`create_train_unit_type` fixed)
- ✓ Drop `TaskSpec.priority` from Pydantic models; use `optional: bool = False`
- ✓ Enforce PascalCase enum values in Pydantic
- ✓ Export JSON Schema from the Pydantic models → published as a build artefact
- ✓ **Follow-up (2026-08-02, `16dc053`):** `Resource` had not actually been
  migrated to the `kind`/`id` discriminator decided in Phase 0 (0d) — it still
  had the old three-nullable-`int`-fields shape (`trackPartId`/`facilityId`/
  `staffId`), missed because it wasn't called out in this checklist even
  though the design doc's per-consumer list always included it. Found while
  investigating the Plan.cpp `Resource` wire-shape bug on the evaluator side
  (see Phase 3 below); fixed to match what solver/evaluator already emit/expect,
  and the exported JSON Schema regenerated.
- ✓ **Follow-up (2026-08-02): `TrainUnit.id`/`IncomingTrainUnit.id`: `string` → `int`.**
  Investigation (prompted by the non-numeric-ID fixture fix above) established
  that every real train unit id on the wire is numeric, and the `"****"`
  placeholder used for "unmatched" departing units was dead code in the
  generator — real unmatched units are built directly with `id=None`, which
  already carries the intended semantics and never went through the code path
  that invented `"****"`. Implemented across all three repos:
  - **Generator** (`4115c7f`): `TrainUnit.id: Optional[int]`,
    `IncomingTrainUnit.id: int` (required), `ShuntingUnit.members`/
    `Action.train_unit_ids: list[int]`; `from_train_unit()`'s `"****"` fallback
    deleted rather than ported.
  - **Solver** (`718a531`): `TrainUnit.Id: uint?`, `IncomingTrainUnit.Id: required uint`,
    `ShuntingUnit.MemberIDs`/`Action.TrainUnitIds: IList<uint>` — same
    nullable/`required` pattern already used for `Carriages`.
  - **Evaluator** (`bf2fcf8`): `HIP_Scenario.proto`/`HIP_Plan.proto` fields
    `string` → `uint64`/`optional uint64`; `stoi()`/`"****"`/`.empty()` guards
    dropped from the two HIP `Train` constructors (kept as-is on the untouched
    legacy `PBTrainUnit` path).
  - Composite/shunting-unit-level ids (`IncomingTrain.id`, `TrainRequest.displayName`,
    `ShuntingUnit.id`/`parentIDs`/`childIDs`) are a separate concept, unaffected,
    still strings. **Superseded 2026-08-08 — see below; they are ints now too.**
  - **Two bugs found and fixed along the way**, both on the evaluator: a stale
    test assertion from the earlier `displayName` fix (`6e0aefa`), and dead
    debug scaffolding in `RunResult::CreateRunResult` that re-parsed the
    scenario file into the legacy (still-string) proto shape purely to write
    a JSON dump to a hardcoded, nonexistent developer path — harmless before
    this change (silently mismatched types were tolerated in unrelated ways),
    hard-failing after it, so removed rather than fixed (`eaa7dad`).
  - Verified end-to-end against all 8 real scenario/plan files (locally built
    images) with no crashes and no new evaluator-side diffs against the
    protobuf baseline beyond the already-known solver-plan-dependent ones.
  - **Not yet done:** none of the three `2.0.0-beta.1` images have been
    re-tagged/re-pushed with these commits yet — same outstanding step as the
    `Resource` fix above.

---

## Phase 3 — Integration testing

Run the full pipeline in this repo against all scenarios and compare to the protobuf baseline.

**Script updates:** ✓ done
- `run_generator.py`/`run_solver.py`/`run_evaluator.py` `DOCKER_IMAGE_VERSIONS["pydantic"]`
  bumped to the `2.0.0-beta.1` ghcr.io tags
- `run_solver.py` and `run_evaluator.py` already glob/read `scenario_*.json` (unified);
  no `scenario_solver_*.json` references remain in any script
- `location.json` already in use throughout

**Run status against `2.0.0-beta.1` images (2026-08-02):**

- ✓ Also cleaned up 9 obsolete `scenario_solver_*.json` fixtures + 1 lowercase-`k`
  duplicate (tracked since `cbc4231`, obsolete since Phase 1 retired the two-file
  scheme) — they were colliding with `run_solver.py`'s `scenario_*.json` glob
  (18 matches instead of 8)
- ✓ `run_generator.py --version pydantic`: 8/8 succeeded, clean unified `scenario_*.json`
  output, no `scenario_solver_*.json` produced
- ✓ `run_solver.py --version pydantic`: 8/8 succeeded
- ✗ **`run_evaluator.py --version pydantic`: 1/9 (only the harmless stale-fixture SKIP);
  all 8 real runs crash — BLOCKING**

**Evaluator crashes found and fixed on `robust-rail-evaluator` (`noproto`) — 3 bugs, 3 fixes:**

1. **`d3d32a3`** — Scenario parsing crashed 8/8 (reported as SIGSEGV, actually an
   uncaught `std::out_of_range` sliced to a bare `std::exception` by `throw e;`
   instead of `throw;`, then `std::terminate`). Root cause: `HIP_Scenario.proto`'s
   `IncomingTrainUnit` wrapped member identity fields in a nested `trainUnit`
   submessage; the real generator output is flat (`{id, typePrefix, carriages,
   tasks}`, same shape `TrainRequest.trainUnits` already used correctly). With
   `ignore_unknown_fields=true` the parser silently dropped the real fields and
   defaulted `typePrefix`/`carriages`, which then failed the
   `(typePrefix, carriages)` lookup. Fixed by flattening the proto to match.
2. **`dc16f21` + `492ddbc`** — After (1), 5/8 files still crashed (2 SIGABRT, 3
   SIGSEGV) further downstream in `Plan.cpp`'s `RunResult::CreateRunResult`.
   Root cause: `HIP_Location.proto`'s `Resource` modeled track/facility refs as
   a proto3 `oneof`, but the solver's real Plan JSON emits `{"kind":
   "trackPart"|"facility", "id": N}` — neither key matched, both silently
   dropped to `0`, which then hit `GetTrackByID("0")` (throws → SIGABRT) or
   `GetFacilityByID(0)` (null deref → SIGSEGV). One root cause, two symptoms;
   fixed by giving `Resource` explicit `kind`/`id` fields matching the real
   wire shape. Also fixed the same exception-slicing bug as (1) in
   `Scenario::Init`, and wrapped `main.cpp`'s scenario load in try/catch so
   load failures fail cleanly instead of crashing.
3. **`38da47d`** — Byte-diff against the protobuf baseline (see run below)
   showed 3 files differing only in truncated type names in human-readable
   output (`"SLT"` instead of `"SLT-4"`). Root cause: the `PB_HIP_TrainUnitType`
   constructor in `Train.h:47` forwarded `typeprefix()` as both the
   `displayName` and `typePrefix` constructor arguments, so `displayName` never
   got the derived `prefix-carriages` form. Fixed by composing it explicitly.

**Resolved, not a code fix — fixture had non-numeric IDs.** 1 of 8 files
(`KleineBinckhorst_48t_custom_larger-example`) used a `"uNN"` prefix for train unit
IDs and `"arr-NN"`/`"dep-NN"` prefixes for shunting-unit-level IDs; both paths hit an
unguarded `stoi()` in the evaluator (`Train.cpp`, `TrainGoal.cpp`) with no non-numeric
fallback, causing a crash. **Confirmed this is not a migration regression** — the
protobuf-era baseline (`evaluations-protobuf/`) crashed identically on this same
scenario. Rather than adding string-ID support to the C++ engine (a real, broader
change — train/shunting-unit IDs are used as `int`/map keys throughout), fixed the
fixture itself: `scenario_config_larger-example.json` (`7dfd203`) now uses plain
numeric-looking ID strings — `"1"`-`"48"` for train units, `"1001"`-`"1024"` /
`"2001"`-`"2024"` for shunting units — matching the convention every other scenario
config in this repo already follows. The scenario now loads and evaluates cleanly,
rejecting only on a legitimate, unrelated data issue (train `1006` longer than its
arrival track) — the same class of clean rejection as the two `random_distribution`
files. No remaining open question here.

**Comparison run (2026-08-02) against `evaluations-protobuf/` baseline**, using a
locally rebuilt `tors:latest` image (includes all 3 fixes above; `2.0.0-beta.1` on
ghcr.io does **not** yet include them — re-tag/re-push still needed):

| File | Result |
|---|---|
| `KleineBinckhorst_10t_random_42s_distribution1` | ✓ byte-identical (correctly rejected, both empty) |
| `KleineBinckhorst_10t_random_42s_distribution2` | ✓ byte-identical (correctly rejected, both empty) |
| `KleineBinckhorst_48t_custom_larger-example` | ✓ byte-identical (both empty — see fixture-fix note above; now a clean scenario-correctness rejection instead of a crash) |
| `KleineBinckhorst_6t_custom_example3` | ✓ byte-identical |
| `KleineBinckhorst_7t_custom_example1` | ✓ byte-identical |
| `simple_service_location_4t_custom_late` | ✓ byte-identical |
| `KleineBinckhorst_30t_random_98s_test` | ~ differs (same verdict, "plan not valid", both sides — differing internal action timings/train-matching, consistent with legitimate solver-side scheduling changes, e.g. the action-sort-collision fix `dc607cd`) |
| `KleineBinckhorst_8t_custom_example2` | ~ differs (same verdict, "Scenario failed: Invalid action" on both sides — one `Wait` action's end timestamp differs, 3420 vs 3154, same solver-side cause as above) |

6/8 byte-identical, 2/8 differ only in solver-plan-dependent details while agreeing on
the top-level pass/fail verdict — not evaluator bugs.

**Still to do before Phase 3 is complete:**
- Rebuild and re-push all three `2.0.0-beta.1` images to ghcr.io: `tors` with
  `d3d32a3`, `dc16f21`, `492ddbc`, `38da47d`, `bf2fcf8`, `6e0aefa`, `eaa7dad`;
  `hip` with `718a531`; `generator` with `16dc053`, `4115c7f`
- Re-run the full pipeline against the re-pushed images (not just local builds)
  to confirm parity
- Decide whether the `KleineBinckhorst_30t`/`6t`/`8t` solver-plan differences
  (route/timing choices that vary by random seed) need deeper solver-side
  diffing to confirm they're benign, or can be accepted as-is

**Pre-existing solver robustness issue found (2026-08-02), not caused by anything
in this session, not fixed — flagging for later:** `KleineBinckhorst_10t_random_42s_distribution2`
intermittently crashes the solver (roughly 1-in-3 runs) with a seed-dependent internal
error — observed as both a `PlanGraph.CheckGraphStructure` `Debug.Assert` failure and,
separately, an unhandled `System.ArgumentException` in `Parking.Deque.Remove`. Confirmed
this is **not** a regression from today's `TrainUnit.id` change: reproduced the *same*
intermittent failure (different stack trace, same file) against the unpatched
`ghcr.io/robust-rail-nl/hip:2.0.0-beta.1` image using the pre-existing string-ID scenario
JSON. This is a real heuristic/local-search robustness gap in
`ServiceSiteScheduling.Solutions.PlanGraph`/`Parking.TrackOccupation`, worth a dedicated
solver-side debugging session at some point, but out of scope for the schema migration work.

**Acceptance criteria:**
- All 8 evaluation files identical (or equivalent) to the protobuf baseline — ✓ 6/8
  identical, 2/8 equivalent (same verdict, differing solver-plan details)
- No `scenario_solver_*.json` files produced or consumed ✓
- `location.json` used throughout; `location_unified.json` and `location_solver.json` retired ✓ (already done on `pydantic` branch)

Results above are from local builds. Once the `hip` solver's pre-existing intermittent
crash (flagged just above) is fixed and `2.0.0-beta.2` images are built and pushed for
all three repos, re-run the pipeline against the real ghcr.io images and update this
section with the confirmed results.

---

## Phase 3b — Loose ends

Things I (LP) noticed and want to write down so we won't forget:

Generator:
- Cleaning up the generator's README.md: it has a TODO that should be dealt
  with
- Make sure the planner can also speak the new schema
- Figure out what to do with the regression-baseline files in the generator
  repo (just delete?).  See also src/generate-scenarios.sh.
- Write a script to validate the various JSON files
- Clean up the generator repo: do (automated) code formatting using
  pre-commit, Ruff etc.
- Decide what to do with unified-schema-design.md.  At least remove
  in-progress bits?

Solver / HIP:
- Fixing the bug occuring in ~1/3 of the cases and noticed by Claude.  Is
  this the same one I opened an issue for?
- Ask Claude for a way to reproduce this bug
- The "merge coinciding Wait actions" commit (e545f33) seems to have
  partially lost its effectiveness: see differences between current (beta.2)
  and legacy (1.4.2) plan versions.
- Look through git diff with main / dev.

Evaluator / TORS:
- Look through git diff with main / dev.
- See if we can get pyTORS to work?  Probably not.
- Fix or delete `EngineTest` and `CompatibilityTest` — see Phase 3c, which is
  blocked on this.
- **Do a focused session on TORS's own search mode.**  TORS does not only
  replay and evaluate a plan; it can also generate one itself, and that looks
  to be what it was originally built for, with plan replay added later.  Worth
  understanding properly: what the search can actually do, whether it is
  usable or useful to us, and where else the two modes' assumptions diverge.

  This matters beyond curiosity.  Nearly every evaluator bug found on
  2026-08-07 was a search-mode primitive behaving wrongly under replay, not a
  bug in its own right:
    - `legal_on_parking_track_rule` rejected a movement ending on a
      non-parking track.  Harmless for the search, which emits step-by-step
      moves that the rule exempts; fatal for replay, where every movement is a
      `MultiMove` and a departure's last movement lands on the gateway.
    - `Wait` runs until the next queued event.  Correct for the search, which
      has no plan and re-decides at every event; wrong for replay, where it
      discards the duration the plan supplied and eats the time reserved for
      whatever follows.
    - `ArriveActionGenerator` hardcodes a zero duration, so a plan cannot
      express a train occupying the gateway while it waits for a route in
      (Robust-Rail-NL/robust-rail-solver#13).
    - `out_correct_time_rule` demanded an exact departure time that an
      outStanding request (time 0) could never satisfy, while the generator
      only offers that exit at the end of the scenario.

  So the two modes share primitives whose contracts only hold in one of them.
  A survey of where else that is true would probably predict the next round of
  bugs rather than waiting to trip over them.

---

## Phase 3d — Every id is an int ✓ DONE

Completes the 2026-08-02 migration, which stopped at the unit-level ids. The
composite ones it deliberately left alone — `IncomingTrain.id`, `Train.id`,
`ShuntingUnit.id`/`parentIDs`/`childIDs`, `NonServiceTraffic.id` — are ints as
of 2026-08-08, across all three repos and every fixture.

**`TrainRequest.displayName` became `id`.** It was never a display name. The
generator assigned it the departing train's id (`src/scenario.py`), the
evaluator derived *two* identities from it (`Outgoing`'s id in `TrainGoal.cpp`
and the id of that request's `ShuntingUnit` in `ShuntingUnit.cpp`), and the
solver's only read printed it as `"train (id)"`. The type information the name
suggested is carried per unit in `trainUnits`, as `(typePrefix, carriages)`.

Two things fell out that are worth keeping:

- **cTORS got simpler, not more complex.** It has represented these ids as
  `int` throughout since long before the JSON migration, and was calling
  `stoi()` on every one of them at the boundary. Four such calls are gone. The
  legacy non-HIP `PBTrainGoal` path keeps its strings, its `stoi()` guards and
  the `"****"` placeholder; it belongs to `--plan_type Evaluator`.
- **A latent sort bug in the solver.** `PlanGraph`'s Wait-merging pass orders by
  `ShuntingUnit.Id`, which over strings sorted unit 10 before unit 2. It is
  numeric now. `GetShuntUnit` also stopped parsing every existing id out of its
  string to mint the next one.

Fixture validation went from 2/19 to 10/19 — every scenario now passes. All
1,921 string ids were numeric, so nothing needed renumbering.

### Left open

- **The nine plans still fail validation**, for two reasons unrelated to ids and
  each needing a decision rather than a conversion:
  - Plans carry `memberIDs` and `standingType`; the model says `members` and
    sets `extra="forbid"`. This is a live disagreement, not a lag — the
    evaluator's `Plan.cpp` raises an error calling `members` the *legacy* field
    and demanding `memberIDs`. Someone has to pick a name.
  - `trainUnitIds` is `null` in all 606 actions, against a schema saying array.
    Either the model accepts `Optional[list[int]]` or the writer emits `[]`.
- **`TrainUnitType.displayName` → `(typePrefix, carriages)`**, which is a
  different field that happens to share a name, and the one this migration is
  sometimes confused with. Already done in the generator (a derived property,
  off the wire), the solver (`TypeDisplayName()` returns the tuple) and every
  fixture. Outstanding only in the evaluator: `TrainUnitType::types` is still
  `map<string, TrainUnitType*>` keyed by the combined string (`Train.h:15`),
  even though `Scenario.cpp:361` already notes the key must be
  `(displayName, carriages)` because the name alone is not unique.
  `TrainUnitTypes.proto:8` retires with it.

---

## Phase 3c — Continuous integration ✓ DONE

Set up CI across all four repos before tagging 2.0.0. The case for doing it now
rather than after: every defect found on 2026-08-07 had been present in every
released version, and each one was invisible to the suites that already existed.
Two of those suites cannot pass at all (see below), which is the sort of thing
that only stays broken when nothing runs them.

Done 2026-08-08. All four repos now have a workflow, on
`claude/2026-08-07-replay-fixes` in each, validated through draft PRs into the
migration branches (solver #15, evaluator #5, generator #10, this repo #7).

### Prerequisite: the two dead-weight evaluator tests ✓ DONE

`EngineTest` and `CompatibilityTest` required `LOCATION_PATH`, `SCENARIO_PATH`
and `PLAN_PATH` to be exported, and then failed with `map::at` against the
bundled demo data — whose `scenario.json` still uses the pre-unification field
names this migration replaced, so they could not have passed even with the
variables set. Resolved 2026-08-08: `ctest` is now 7/7.

`CompatibilityTest` was rebuilt around a committed fixture
(`data/Demo/hip_plan_evaluation_test`) covering the HIP plan path the pipeline
actually runs, and demonstrably catches the `4482fa2` defect. `EngineTest` kept
only its self-contained scenario-unification case; its two environment-driven
cases were deleted.

**Coverage this leaves open.** The deleted `EngineTest` "Plan test" was the only
test naming the cTORS-native plan path — `GetRunResultProto` plus
`RunResult::CreateRunResult(const Location*, const PBRun&)` — which `main.cpp`
still reaches via `--plan_type Evaluator`. Nothing was lost in practice, since it
never ran, but that mode now has no test at all and the pipeline never uses it:
`run_evaluator.py` always passes `--plan_type Solver`. Decide whether the mode is
still supported. If it is, it wants a fixture like the HIP one; if it is not,
retiring it removes a second plan format from the evaluator.

### What each repo runs

| repo | workflow | check |
|---|---|---|
| `robust-rail-generator` | `.github/workflows/python.yml` | `pytest` (14); `schema/*.json` still matches `model_json_schema()` |
| `robust-rail-solver` | `.github/workflows/dotnet.yml` | `csharpier check`; build; no-config smoke run; tests (35) |
| `robust-rail-evaluator` | `.github/workflows/ctest.yml` | configure, build, `ctest` (7/7) |
| `scenario-planning-inputs` | `.github/workflows/validate-fixtures.yml` | generator schema freshness (gating); fixture validation (report-only) |

All four trigger on push and pull request against the stable branches and the
relevant migration branch (`noproto` or `pydantic`), plus `workflow_dispatch`.
No `claude/**` wildcard, so work on a session branch is validated by opening a
PR into the migration branch — which is enough, because the `pull_request` event
runs the workflow from the merge commit, so a workflow added in the PR does run.

`dotnet build` warnings-as-errors remains a separate decision; the solver builds
with two nullable warnings in `Initial/SimpleHeuristic.cs`.

**The solver's workflow was red before any of this, for a reason worth
recording.** It had never run on `noproto` — the triggers named only `main` and
`dev` — but PR #12 into `main` did fire it on 2026-08-03, and it failed in 29s.
The no-config default run in `Program.cs` had been given an absolute
`/home/leon/Projects/...` prefix, so it worked on exactly one machine. Fixing
the triggers alone would have left it red. The paths are relative again, as they
were on `dev`.

### Schema validation in this repo

`location.json`, `scenarios/*.json` and `plans/*.json` are validated against the
generator's exported schemas. This closes a real gap: several fixtures have been
edited by hand — the ID migration and the electrification fix were both bulk
edits — and nothing checked the result until a tool fell over on it, usually
with a bad error message.

Two caveats, both encoded in the workflow:

- **The check does not gate yet.** It reported 2 of 18 fixtures valid when the
  workflow was written — the two `location.json` files. Phase 3d took that to
  10 of 18 by making every id an int; all eight scenarios now pass.

  The nine plans still fail, for the two reasons recorded under Phase 3d, both
  of which need a decision and not a conversion: `memberIDs` vs `members` (plus
  `standingType` against `extra="forbid"`), and `trainUnitIds` being `null` in
  all 606 actions. Failing the branch on known drift only teaches everyone to
  ignore the check, so it runs under `continue-on-error` until then. **Next step
  for this repo: settle those two, then drop `continue-on-error`.**
- **Where the schemas come from is still open**, and is the least settled part
  of this setup.

  The workflow clones `robust-rail-generator` and reads `schema/` from it. A
  copy vendored into this repo would instead go stale in silence, which is
  worse: a stale schema does not fail, it passes, having checked the wrong
  contract. So the workflow also re-exports the schemas in that checkout and
  fails if they differ from what is committed there — and *that* step gates,
  even while the fixture validation itself does not.

  **Which branch it clones caused a real false reading on 2026-08-08.** It was
  pinned to `pydantic`, so the first run after the id migration validated the
  newly converted fixtures against the pre-migration schema and reported 2/18
  for a tree that was really at 10/18. The freshness gate passed throughout,
  because that schema was perfectly consistent — with the wrong models. The
  branch is now chosen to match: same name in the generator if it exists,
  `pydantic` otherwise. That is enough for coordinated changes, which land in
  both repos on one branch, but it is a naming convention standing in for a
  contract, and it will mislead anyone who does not follow it.

  **Where this should end up.** `schemaVersion` already exists on every fixture,
  the generator already has `EXPECTED_SCHEMA_VERSION`, and the evaluator already
  has `SchemaVersionTest`. Publishing the exported schemas as a release artifact
  keyed by `schemaVersion` (the Phase 2 item) and validating each fixture against
  *the version it declares* removes the branch guess and the staleness together,
  and makes mixed-version fixtures during a migration expressible rather than
  simply broken. Worth deciding once the release settles and schema changes
  become rare and individually versioned.

**`scenario_config_*.json` stays out of scope.** It has no schema. It is
validated by `check_config.py`, which is a list of presence checks and rejects
nothing it does not recognise. That is load-bearing: the `intent` blocks added
to the new configurations rely on unknown keys passing through untouched. If a
config schema is ever written, it has to permit `intent`, or those
configurations become invalid.

---

## Phase 4 — Stable release

- Tag `generator:2.0.0`, `hip:2.0.0`, `tors:2.0.0` once integration tests pass
- Archive the `*-protobuf` and `*-pydantic` versioned directories in this repo
  (keep as historical reference; remove from the active pipeline)
- Update `README.md` in this repo to reflect the stable pipeline

---

## Sequencing

```
Phase 0 (decisions)
  ├─► Phase 1a (schemaVersion — all three repos)
  └─► Phase 1 (scenario unification — all three repos) ◄─► Phase 2 (generator cleanup)
          └─► Phase 3 (integration tests)
                  └─► Phase 4 (release tags)
```

Phase 1a and Phase 1 can proceed in parallel once Phase 0 decisions are resolved.
Work within each phase can be split across the three repos and done concurrently.
Phase 3 requires all three repos to be updated and re-tagged before it can run.
