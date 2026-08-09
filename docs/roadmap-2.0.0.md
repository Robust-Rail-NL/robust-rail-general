# Roadmap: 2.0.0 release of generator, HIP, and TORS

## Status

The unified interchange schema is frozen and implemented across all five repos.
The pipeline runs end-to-end on published images, all five repos have gating CI,
and the release evidence is recorded under [Release evidence](#release-evidence)
below.

**One thing gates rc.1:** Robust-Rail-NL/robust-rail-solver#11, the intermittent
crash in `Deque`/`TrackOccupation`. It has a deterministic reproduction as of
2026-08-09 and is being fixed rather than documented, by decision.

Everything else outstanding is either a decision with no defect behind it, or a
known issue to name in the release notes.

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

## Open — the rc.1 gate

**solver#11 — `Deque.Remove` on a node that is not in the deque.**

Reproduces deterministically once the *solver* seed varies:
`run_solver.py` pins `Seed: 1`, which is why four consecutive pipeline runs give
byte-identical plans and never crash. Sweeping the seed over
`KleineBinckhorst_10t_random_42s_distribution2`, seeds 2/4/6/8/10/12 crash and
the odd ones pass.

Established: the same `TrackTask` is departed **twice**, on the correct
occupation, within a single `ComputeModel` pass. Nothing detects it because
`State.HasDeparted` is cleared only by `State.Reset()`, `Arrive` never clears it,
and `Depart` never consults it.

`641e380` added a fail-fast membership check to `Deque.Remove` (O(1) always, plus
an exhaustive walk under `DEBUG`). It does not change which seeds fail — it makes
the failure land closer to the cause. Its exhaustive check never fired on a
passing seed, so **plans produced under `Seed: 1` are not built on a corrupted
deque**, which had been an open worry about the committed fixtures.

Still open: which two call sites make the pair —
`PlanGraph.ComputeLocation:197` and/or `PlanGraph.computeDepartureRoutes:769`.
That decides whether the fix removes a redundant call or repairs a loop that
revisits a task. The full brief, including a retracted intermediate conclusion
and the instrument that caused it, is in solver#11's comments.

---

## Open — known issues to name in the release notes

| issue | effect |
|---|---|
| solver#13 | Solver parks on non-parking arrival tracks when it cannot move into the yard immediately. Blocks `6t_custom_example3`. |
| solver#14 | outStanding trains have no deadline in the cost function, so plans over-run the scenario horizon for free. Produces the plan that trips evaluator#6. |
| evaluator#6 | `EvaluatePlan` spins when the plan still has actions but the state is terminal, reporting the symptom rather than "plan extends past the horizon". Terminates via a safety valve; blocks nothing, but the diagnostic misleads. Blocks `7t_custom_example1`. |
| solver#16 | `Deque.RemoveHead(Side)` throws unconditionally, including after removing successfully. Latent — no callers. |
| evaluator#1 | Invalid JSON for PB parsing fails quietly. On the legacy `--plan_type Evaluator` path only. |

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

### Where the exported schemas should live

`validate-fixtures.yml` clones `robust-rail-generator` and reads `schema/` from
the branch of the same name. Vendoring a copy here would be worse — a stale
schema does not fail, it passes, having checked the wrong contract — so the
workflow also re-exports the schemas in that checkout and gates on them matching
what is committed there.

The branch guess has already produced one false reading: pinned to `pydantic`, a
run validated newly migrated fixtures against the pre-migration schema and
reported 2/18 for a tree really at 10/18, while the freshness gate stayed green
because that schema was perfectly consistent with the wrong models.

**Where this should end up:** publish the exported schemas as a release artifact
keyed by `schemaVersion`, and validate each fixture against *the version it
declares*. That removes the branch coupling and the staleness together, and makes
mixed-version fixtures during a migration expressible rather than simply broken.
Worth deciding once schema changes become rare and individually versioned.

### `planning-approach/pipeline.py`

Still assumes the two-file scenario world Phase 1 removed: it reads
`location_solver.json`, which no longer exists, and pairs `scenario_solver_*.json`
with `scenario_*.json` by string replacement. `GENERATE_DIR` points into this
repo, so it breaks against current contents. Deciding what its inputs are now is
a design question, not a rename. Its CI does not cover it — the reading tests
exercise `converter.py`, not `pipeline.py`. Recorded in
`planning-approach/SCHEMA_STATUS.md`, along with the visualizer's
`member_lengths_from_scenario` and the un-reconvertible `test_data/`.

---

## Open — loose ends

Things I (LP) noticed and want to write down so we won't forget:

Generator:
- Clean up the generator's README.md: it has a TODO that should be dealt with
- Make sure the planner can also speak the new schema
- Figure out what to do with the regression-baseline files in the generator repo
  (just delete?). See also `src/generate-scenarios.sh`.
- Clean up the generator repo: automated formatting with pre-commit, Ruff etc.
- Decide what to do with `unified-schema-design.md`. At least remove in-progress
  bits?

Solver / HIP:
- The "merge coinciding Wait actions" commit (`e545f33`) seems to have partially
  lost its effectiveness: see differences between current and legacy (1.4.2) plan
  versions.
- Look through `git diff` with `main` / `dev`.
- `dotnet build` warnings-as-errors is a separate decision; the solver builds with
  two nullable warnings in `Initial/SimpleHeuristic.cs`.

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

**Do not assume the next solver bump is as cheap.** `641e380` only added throws
on paths that were already corrupt, so it could not change a healthy run. A fix
for solver#11 will not have that property: removing a redundant `Depart` changes
what the parking model computes, so plans can legitimately differ. If they do,
the committed plan fixtures and the verdict table above have to be regenerated
rather than re-confirmed — a change to the release evidence, not a formality.
Check the verdicts, not just whether the files differ: a plan changing is
expected, a *verdict* changing is a finding.

### What this run does not cover

- x86-64 only. arm64 is covered at the unit-test level (evaluator and solver CI
  matrices, 2026-08-09) but the pipeline has never run there. A cross-arch
  comparison would not be meaningful anyway — different machine, and the
  determinism guarantee is conditional on not exhausting the time budget.
- solver#11 did not fire. At roughly 1 in 3 under a varying seed that is
  unsurprising, and is not evidence of absence.

---

## Phase 4 — Stable release

- Tag `generator:2.0.0`, `hip:2.0.0`, `tors:2.0.0`
- Release notes naming solver#13, solver#14 and evaluator#6, and the two fixtures
  expected to fail because of them
- Archive the `*-protobuf` and `*-pydantic` versioned directories in this repo
  (historical reference; remove from the active pipeline), and retire the
  `legacy` entries from the `--version` selectors with them
- Update this repo's `README.md` to reflect the stable pipeline
- Merge `release/2.0.0` into each repo's stable branch and delete it

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
