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
| 0b | Confirm `displayName` cleanup: `"SLT"` + `carriages: 4` instead of `"SLT4"` | Generator, HIP, TORS all read this field |
| 0c | `TaskSpec.priority`: confirm it can be dropped everywhere | Generator output; HIP C# has a TODO comment |
| 0d | `Resource` discriminator: keep "exactly one of three nullables" or introduce an explicit `kind` field? | Wire-format decision; conservative choice = keep current shape |
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

**`robust-rail-generator`**
- Update Pydantic models to the unified (HIP) field names
- Stop emitting `scenario_solver_*.json`; emit one `scenario_*.json` per case
- Bump to `generator:2.0.0`

**`robust-rail-solver` (HIP, C#)**
- Switch to reading `scenario_*.json` (currently reads `scenario_solver_*.json`)
- Field names already match HIP naming — mainly a path change
- Additional breaking changes driven by Phase 0 decisions:
  - `TrainUnit.Type` (embedded object) → `TypeDisplayName` (string reference); drop `Type`
  - `ShuntingUnit.Members` (embedded) → `MemberIDs` (string list); drop `Members`
  - Extend `PredefinedTaskType` enum: add `StandIn`, `StandOut`, `Walking`, `Break`, `NonService`
  - Drop `TaskSpec.Priority` (once 0c confirmed)
  - `displayName` cleanup (once 0b confirmed)
- Bump to `hip:2.0.0`

**`robust-rail-evaluator` (TORS, C++)**
- Retire `EvaluatorScenario` (legacy non-HIP shape); update reader to unified field names
- No `Plan.trackParts` work needed — TORS already ignores this field entirely; all
  infrastructure is loaded from `--path_location` via `LocationEngine`
- Bump to `tors:2.0.0`

---

## Phase 2 — Generator schema cleanup

These are generator-internal changes with no consumer impact, and can proceed in parallel
with Phase 1 once Phase 0 decisions are in:

- Drop protobuf dependency (`py_protobuf/`, `google-protobuf` package)
- Finalise `displayName` (if 0b confirmed: `"SLT"` + `carriages: 4`)
- Drop `TaskSpec.priority` from Pydantic models (if 0c confirmed)
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
- `location_unified.json` used throughout; `location.json` / `location_solver.json` retired

Update `docs/protobuf-pydantic-comparison.md` with final run results.

---

## Phase 4 — Release

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
