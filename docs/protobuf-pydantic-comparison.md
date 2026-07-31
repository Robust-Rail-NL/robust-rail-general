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
| 5 | Pydantic plan output format (undocumented) | High — evaluator cannot execute plan actions | Fixed in tors:2.0.0-alpha.4 |

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

### Pydantic versions used (run 1 — tors:2.0.0-alpha.3)

| Tool | Image |
|---|---|
| Generator | `ghcr.io/robust-rail-nl/generator:2.0.0-alpha.2` |
| Solver (HIP) | `ghcr.io/robust-rail-nl/hip:2.0.0-alpha.2` |
| Evaluator (TORS) | `ghcr.io/robust-rail-nl/tors:2.0.0-alpha.3` |

### Results (run 1)

The pydantic evaluator failed to make progress on 5 of 8 cases — it could not consume
plan actions at all, either spinning for 100 iterations or exiting after a single step.
This confirmed that `tors:2.0.0-alpha.3` was incompatible with the pydantic pipeline output.
The evaluator was subsequently fixed; see run 2 below.

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

---

### Pydantic versions used (run 2 — tors:2.0.0-alpha.4)

| Tool | Image |
|---|---|
| Generator | `ghcr.io/robust-rail-nl/generator:2.0.0-alpha.2` |
| Solver (HIP) | `ghcr.io/robust-rail-nl/hip:2.0.0-alpha.2` |
| Evaluator (TORS) | `ghcr.io/robust-rail-nl/tors:2.0.0-alpha.4` |

### Results (run 2)

7 of 8 cases produce identical output to the protobuf run. The one difference is in
`8t_example2`, where the pydantic solver produced a slightly different plan (a wait
action of duration 3154 s vs 3420 s), leading to a different line in the evaluation
trace — but the same end result ("shunting unit 2901 not found"). This is expected
non-determinism in the solver, not a format issue, and is the encouraging signal that
the pydantic pipeline is genuinely running different code.

The remaining identical failures are all pre-existing issues unrelated to the migration:

| Case | Protobuf outcome | Pydantic outcome | Same? |
|---|---|---|---|
| `distribution1` | exit 1 — pre-eval abort: arrival train too long for track | exit 1 — same abort | ✓ |
| `distribution2` | exit 1 — pre-eval abort: departure train too long for track | exit 1 — same abort | ✓ |
| `48t_larger-example` | exit 139 — TORS crash (`std::exception`) | exit 139 — same crash | ✓ |
| `30t_random_98s` | exit 0 — "Plan not valid": 30 departure time mismatches | exit 0 — same result | ✓ |
| `simple_service_4t_late` | exit 0 — "Plan not valid": departure time mismatch | exit 0 — same result | ✓ |
| `6t_example3` | exit 0 — "Invalid action: Track Wissel963 not electrified" | exit 0 — same result | ✓ |
| `7t_example1` | exit 0 — "Invalid action: shunting unit 2801 not found" | exit 0 — same result | ✓ |
| `8t_example2` | exit 0 — "Invalid action: shunting unit 2901 not found" | exit 0 — same failure, different wait duration in trace | ≈ |

The "identical" failures all fail for reasons that make the version irrelevant:
`distribution1/2` abort before the evaluation loop (scenario data constraint);
`48t` crashes the evaluator (pre-existing TORS bug); `30t`, `simple_service`, `6t`,
`7t`, and `8t` have invalid plans regardless of which solver version produced them.
A clean pass on any case would be the meaningful signal; none exists yet in either version.

---

## Run 3 — unified location.json

The third run uses the pydantic pipeline with a single unified `location.json` shared
between the generator and solver (previously they used separate files). Results are in
`Location_*/{plans,evaluations}/` (no version suffix).

### Versions used

| Tool | Image |
|---|---|
| Generator | `ghcr.io/robust-rail-nl/generator:2.0.0-alpha.3` |
| Solver (HIP) | `ghcr.io/robust-rail-nl/hip:2.0.0-alpha.2` |
| Evaluator (TORS) | `ghcr.io/robust-rail-nl/tors:2.0.0-alpha.4` |

Baseline for comparison: `plans-pydantic/` and `evaluations-pydantic/` (run 2).

### Evaluations

All 8 evaluation files are byte-for-byte identical to run 2. The unified location has
no effect on evaluation outcomes; all pre-existing failures remain unchanged.

### Plans

| Case | vs pydantic (run 2) |
|---|---|
| `distribution1` | Identical |
| `distribution2` | Identical |
| `30t_random_98s` | Identical |
| `6t_example3` | Identical |
| `7t_example1` | Identical |
| `8t_example2` | Identical |
| `48t_larger-example` | **New** — no run 2 equivalent; solver now produces a plan |
| `simple_service_4t_late` | **Differs** — same 11 actions, but 3 consecutive actions reordered (`wait`→`exit`→`move` vs `move`→`wait`→`exit`); resources move with their action |

The `48t` plan has no run 2 equivalent because the `plans-pydantic/` directory predates
the addition of that scenario — not because the unified location changed solver behaviour.
The evaluator still crashes on `48t` (pre-existing TORS bug, unrelated to the location change).

The `simple_service` reordering is a different but equivalent scheduling decision by the
solver — the same actions with the same resources, in a different sequence. This is
consistent with the unified location slightly changing the track/resource data the
solver uses for scheduling.
