# Generator output comparison: Protobuf vs Pydantic

This document records the differences found in scenario JSON files produced by the
`robust-rail-generator` during its migration from Protobuf to Pydantic serialisation.

## Setup

Both versions were run with `run_generator.py` over the same set of
`configurations/scenario_config_*.json` inputs.

| Path | Source |
|---|---|
| `Location_*/scenarios-protobuf/` | Protobuf-based generator (`generator:0.1`) |
| `Location_*/scenarios/` | Pydantic-based generator (`generator:0.2`) |

Files compared: 7 non-solver scenarios + 7 `scenario_solver_*` files across
`Location_KleineBinckhorst` and `Location_SimpleService`.

---

## Differences

### Category 1 — Numeric fields: strings (protobuf) → integers (pydantic)

**Status: expected, likely harmless**

Protobuf's `MessageToDict` serialises 64-bit integers as JSON strings (per the proto3
JSON encoding spec). Pydantic serialises them as native JSON numbers.

Affected fields:

- Top-level: `startTime`, `endTime`
- `in / out / inStanding / outStanding [*]`: `time`, `parkingTrackPart`, `sideTrackPart`, `standingIndex`
- `trainUnitTypes [*]`: `backAdditionTime`, `backNormTime`, `combineDuration`, `splitDuration`, `startUpTime`, `travelSpeed`

Example:

```json
// protobuf
"endTime": "9600"

// pydantic
"endTime": 9600
```

---

### Category 2 — Optional fields: default values (protobuf) → `null` (pydantic)

**Status: semantically equivalent, verify with consumers**

Protobuf emits the zero/false default for optional fields; Pydantic models them as
nullable and emits `null` when unset.

| Field | Protobuf | Pydantic |
|---|---|---|
| `trainUnitTypes[*].idPrefix` | `0` | `null` |
| `trainUnitTypes[*].reversalDuration` | absent (new field) | `null` |
| `in / out [*].canDepartFromAnyTrack` | `false` | `null` |
| `out / inStanding [*].standingIndex` | `0.0` | `null` |

---

### Category 3 — Member fields `id` and `tasks`

**Status: partially resolved; two sub-issues remain**

In the first Pydantic build, `id` and `tasks` were absent from all members in `in`,
`out`, `inStanding`, and `outStanding` trains. After regeneration with a fixed build
these fields are present. Two differences remain:

#### 3a — Outgoing train member `id`: `'****'` → `null`

In `out` (and `outStanding`) trains, individual train unit IDs are not yet assigned,
because these are departure *requests* rather than specific units. Protobuf used the
string `'****'` as a placeholder; Pydantic emits `null`. Both represent the same
concept (no ID assigned), using different sentinels.

```json
// protobuf
{ "id": "****", "typeDisplayName": "SNG-3", "tasks": [] }

// pydantic
{ "id": null, "typeDisplayName": "SNG-3", "tasks": [] }
```

#### 3b — Task fields for non-predefined tasks

Two fields differ when a task uses `"other"` (non-predefined) type:

**`type` object** — Pydantic adds `"predefined": null`; Protobuf omits absent fields:

```json
// protobuf
"type": { "other": "Reinigingsperron" }

// pydantic
"type": { "predefined": null, "other": "Reinigingsperron" }
```

**`priority`** — Protobuf emits the value; Pydantic emits `null`:

```json
// protobuf
"priority": 1

// pydantic
"priority": null
```

The `priority` drop warrants attention: if the solver or evaluator uses this field for
task scheduling, emitting `null` instead of `1` may change behaviour.

---

### Category 4 — Solver scenario: structural differences

**Status: confirmed broken end-to-end; plan format from pydantic solver likely incompatible with pydantic TORS**

The `scenario_solver_*` files show more substantial structural changes.

#### 4a — `in` / `out` / `inStanding` / `outStanding`: dict wrapper removed

Protobuf wraps each collection in a named dict; Pydantic emits the list directly.

```json
// protobuf
"in": { "trains": [ ... ] }
"out": { "trainRequests": [ ... ] }

// pydantic
"in": [ ... ]
"out": [ ... ]
```

#### 4b — Train members: inline type object → `typeDisplayName` string

Protobuf embeds a full `trainUnit.type` object inside each member; Pydantic replaces
this with a single `typeDisplayName` string (e.g. `"SLT-4"`).

```json
// protobuf
{ "trainUnit": { "id": "2401", "type": { "displayName": "SLT", "carriages": 4, ... } }, "tasks": [...] }

// pydantic
{ "typeDisplayName": "SLT-4", "id": null, "tasks": [...] }
```

#### 4c — New top-level fields in pydantic (absent in protobuf)

| Field | Value in pydantic |
|---|---|
| `trainUnitTypes` | Full list of all train unit type definitions |
| `disabledTrackPart` | `[]` |
| `nonServiceTraffic` | `[]` |
| `workers` | `[]` |

---

## Summary table

| # | Difference | Impact | Status |
|---|---|---|---|
| 1 | Numeric strings → ints | Low — most parsers accept both | Expected |
| 2 | Default values → `null` | Low — semantically equivalent | Verify with consumers |
| 3a | Out member `id`: `'****'` → `null` | Low — both are "unassigned" sentinels | Acceptable |
| 3b | Task `type` gains `predefined: null` | Low | Acceptable |
| 3b | Task `priority`: `1` → `null` | Medium — may affect scheduling | Needs fix |
| 4a | `in`/`out` wrapper dict removed | High — likely breaking for HIP | Confirmed broken |
| 4b | Member type object → `typeDisplayName` | High — structural change | Confirmed broken |
| 4c | New top-level fields added | Low — additive | Acceptable |
| 5 | Pydantic plan output format (undocumented) | High — evaluator cannot execute plan actions | Needs investigation |

---

## End-to-end evaluation results

Both pipeline versions were run in full (generator → solver → evaluator) over the same inputs.
Results are in `Location_*/evaluations-{protobuf,pydantic}/`.

### Protobuf versions used

| Tool | Image |
|---|---|
| Generator | `ghcr.io/robust-rail-nl/generator:1.2.0` |
| Solver (HIP) | `ghcr.io/robust-rail-nl/hip:1.4.1` |
| Evaluator (TORS) | `ghcr.io/robust-rail-nl/tors:1.3.0` |

### Pydantic versions used

| Tool | Image |
|---|---|
| Generator | `ghcr.io/robust-rail-nl/generator:2.0.0-alpha.2` |
| Solver (HIP) | `ghcr.io/robust-rail-nl/hip:2.0.0-alpha.2` |
| Evaluator (TORS) | `ghcr.io/robust-rail-nl/tors:2.0.0-alpha.3` |

### Results

8 pairs compared across `Location_KleineBinckhorst` (7) and `Location_SimpleService` (1).
No case yields a clean pass in either version.

| Case | Protobuf outcome | Pydantic outcome | Same? |
|---|---|---|---|
| `distribution1` | exit 1 — pre-eval abort: arrival train too long for track | exit 1 — same abort | ✓ |
| `distribution2` | exit 1 — pre-eval abort: departure train too long for track | exit 1 — same abort | ✓ |
| `48t_larger-example` | exit 139 — TORS crash (`std::exception`) | exit 139 — same crash | ✓ |
| `30t_random_98s` | exit 0 — "Plan not valid": 30 departure time mismatches | exit 0 — one simulation step; no verdict | ✗ |
| `simple_service_4t_late` | exit 0 — "Plan not valid": departure time mismatch | exit 0 — one simulation step (0 events); no verdict | ✗ |
| `6t_example3` | exit 0 — "Invalid action: Track Wissel963 not electrified" | exit 0 — `EvaluatePlan` stuck at T300 for 100 iterations; aborted | ✗ |
| `7t_example1` | exit 0 — "Invalid action: shunting unit 2801 not found" | exit 0 — `EvaluatePlan` stuck at T0 for 100 iterations; aborted | ✗ |
| `8t_example2` | exit 0 — "Invalid action: shunting unit 2901 not found" | exit 0 — `EvaluatePlan` stuck at T0 for 100 iterations; aborted | ✗ |

#### Group A — Identical outcome in both versions (3 cases)

| Case | Outcome | Root cause |
|---|---|---|
| `distribution1` | Both exit 1, empty eval file | Pre-eval abort: arrival train length (270.6 m) exceeds track [15] length (255 m) |
| `distribution2` | Both exit 1, empty eval file | Pre-eval abort: departure train length (270.6 m) exceeds track [15] length (255 m) |
| `48t_larger-example` | Both exit 139, empty eval file | TORS crash: `terminate called after throwing std::exception` (SIGSEGV) |

These failures are pre-existing data or evaluator issues unrelated to the migration.

#### Group B — Different failure mode (5 cases)

All five fail in both versions, but the pydantic evaluator fails in a qualitatively different way.

| Case | Protobuf outcome | Pydantic outcome |
|---|---|---|
| `30t_random_98s` | "Plan not valid" — 30 departure time mismatch errors | Evaluator exits after one simulation step; no verdict written |
| `simple_service_4t_late` | "Plan not valid" — departure time mismatch | Evaluator exits after one step (0 events queued); no verdict |
| `6t_example3` | "Invalid action: Track Wissel963 not electrified" | `EvaluatePlan` stuck at T300 for 100 iterations; aborted |
| `7t_example1` | "Invalid action: shunting unit 2801 not found" | `EvaluatePlan` stuck at T0 for 100 iterations; aborted |
| `8t_example2` | "Invalid action: shunting unit 2901 not found" | `EvaluatePlan` stuck at T0 for 100 iterations; aborted |

The protobuf evaluator can read the plan, execute actions, and report specific failures.
The pydantic evaluator either exits immediately after setting up the simulation or spins
unable to advance the plan iterator — it cannot consume plan actions at all.

### Analysis

The evaluator (TORS) reads two inputs: the regular scenario (`scenario_<X>.json`,
affected by categories 1–3) and the plan (`plan_<X>.json`, produced by the HIP solver).
Categories 1–3 are low-impact and do not explain the "no progress" failure pattern.

The most likely root cause is that **the pydantic solver produces plans in a different
format** that TORS 2.0.0-alpha.3 cannot interpret. This is a downstream effect of
Category 4: the structural changes in the solver scenario format (`scenario_solver_<X>.json`)
feed into the solver, which may have changed what it writes into `plan_<X>.json`.
The comparison document does not yet cover solver plan output format — that is the
key missing piece.

Category 3b (`priority`: 1 → `null`) remains a declared concern but could not be
confirmed or ruled out from these results, as the evaluator never reaches task
scheduling in any of the Group B cases.
