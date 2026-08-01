# Roadmap: 2.0.0 release of generator, HIP, and TORS

## Context

The pydantic pipeline (generator:2.0.0-alpha.3, hip:2.0.0-alpha.2, tors:2.0.0-alpha.4) now
runs end-to-end on a single `location_unified.json`. Evaluations are equivalent to the protobuf
baseline (see `docs/protobuf-pydantic-comparison.md`). The remaining work before stable 2.0.0
releases falls into four areas:

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

**`robust-rail-generator`** — Phase 1 complete for scenario unification; Phase 2 cleanup pending

Completed (branch `pydantic`):
- ✓ Emits one unified `scenario_*.json` (HIP field names); `scenario_solver_*.json` retired
- ✓ `scenario-planning-inputs/run_solver.py` updated to read `scenario_*.json`
- ✓ `location_unified.json` renamed to `location.json`

Remaining work (Phase 2 — see below).

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

Solver and evaluator have both completed Phase 1; generator completed Phase 1 in an
earlier session (scenario unification, `location.json` rename). All three repos have
now finished Phase 1 scope. Remaining before the coordinated beta tag:
- `tors:2.0.0-beta.1` and `hip:2.0.0-beta.1` already tagged
- `generator` is still `2.0.0-alpha.3` — **decided:** tag `generator:2.0.0-beta.1` once
  Phase 2 cleanup (below) lands, not on Phase 1 scope alone, since Phase 2 is generator-
  internal and already unblocked

The stable `2.0.0` release follows once integration tests pass (Phase 3).

---

## Phase 2 — Generator schema cleanup

These are generator-internal changes. All Phase 0 decisions are now resolved,
so this phase is unblocked.

- Drop protobuf dependency (`py_protobuf/`, `google-protobuf` package)
- Implement `typePrefix`/`carriages` identity in Pydantic models:
  - Rename `display_name` → `type_prefix` on `TrainUnitType`
  - Add `type_prefix: str` + `carriages: int` to `TrainUnit` as the type reference
  - `typeDisplayName()` becomes a derived helper: `type_prefix + "-" + str(carriages)`
  - Fix `add_custom_train_unit_types`: read `unit_type["typePrefix"]` (camelCase),
    not `unit_type.get("type_prefix", None)` (was always reading `None`)
  - Fix `create_train_unit_type`: actually store `type_prefix` on the model object
    (currently accepted as a parameter but silently dropped)
- Drop `TaskSpec.priority` from Pydantic models; use `optional: bool = False`
- Enforce PascalCase enum values in Pydantic (`Move = "Move"`, not `Move = "move"`)
- Export JSON Schema from the Pydantic models → published as a build artefact

---

## Phase 3 — Integration testing

Run the full pipeline in this repo against all scenarios and compare to the protobuf baseline.

**Script updates needed:**

| Script | Change |
|---|---|
| `run_generator.py` | No longer produce `scenario_solver_*.json` |
| `run_solver.py` | Point `--path_scenario` at `scenario_*.json` (unified), not `scenario_solver_*.json` |
| `run_evaluator.py` | No change expected; already reads `scenario_*.json` |

`location_unified.json` is already in use throughout. ✓

**Acceptance criteria:**
- All 8 evaluation files identical (or equivalent) to the protobuf baseline
- No `scenario_solver_*.json` files produced or consumed
- `location.json` used throughout; `location_unified.json` and `location_solver.json` retired ✓ (already done on `pydantic` branch)

Update `docs/protobuf-pydantic-comparison.md` with final run results.

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
