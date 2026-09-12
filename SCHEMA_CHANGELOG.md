# Schema changelog

Tracks changes to the shared interchange `schemaVersion`, carried on
`Location`, `Scenario`, and `Plan` (see `unified-schema-design.md` in
`robust-rail-generator`). This is independent of the tool release versions
(`generator`, `hip`, `tors`) — it increments only on breaking changes to the
wire format, and all three repos bump their local `EXPECTED_SCHEMA_VERSION`
together when it does.

Mismatch behaviour is warn-and-continue: a missing or unexpected
`schemaVersion` produces a logged warning, not a hard reject. That default is
planned to loosen starting at version 2 (see below), once it lands: one
specific plan shape will become a hard reject, gated on the plan's own
declared `schemaVersion` rather than on this mismatch warning.

Moved here from `robust-rail-generator` on 2026-09-10, alongside the rest of
`src/models/` (see `docs/roadmap-2.0.0.md`, "Where the exported schemas
should live") — the models this changelog tracks have lived in this repo
since 2026-08-20, and this file just hadn't caught up until now. Entries
below predating the move still say "the generator" where that was
accurate at the time; only the file's own location was stale, not what it
says happened.

## 2 — planned

**Not yet released.** The three changes below are code-complete on branches
across every affected repo (this one, `robust-rail-solver`,
`robust-rail-evaluator`, `robust-rail-planner`) but none of it has merged to
any repo's `main` yet — every producer and consumer still speaks
`schemaVersion: 1` today. This entry is deliberately a separate commit on top
of the "landed" wording (see that commit for the original text) rather than
an edit to it, so that once schemaVersion 2 actually lands, reverting this
commit and filling in the real date restores the original present-tense
entry instead of requiring it to be rewritten from scratch.

Three related changes, to land together:

- `PredefinedTaskType.Walking` renamed to `Setback`. `Walking` named a
  shunting-unit reversal action after the crew's part in it (walking to the
  other end, which is why it takes time) rather than what the action
  represents. Moved out of the "Staff / facility" grouping into "Movement",
  where it actually belongs.
- A `Move` action whose route embeds an unflagged reversal (the same track
  revisited two hops apart, e.g. `[..,X,Y,X,..]`) is no longer accepted for
  a plan declaring `schemaVersion: 2` or later — it must use an explicit
  `Setback` action instead. A plan declaring `schemaVersion: 1` (or none)
  keeps evaluating exactly as before: still tolerated, with a deprecation
  warning.
- `Plan` gains `feasibility` (`Feasibility` enum: `Feasible`/`Infeasible`/
  `Unknown`, defaults to `Unknown`), and optional `producer` (free text,
  e.g. `"robust-rail-solver 2.0.0-edge+20260826.a1b2c3d"`), `cost` (number),
  and `costDetails` (free-form breakdown string, e.g. the solver's own
  `SolutionCost.ToString()` output) fields. `feasibility` is a producer's own
  verdict on whether *this specific submitted plan* satisfies all hard
  constraints — not a claim about whether some other plan for the same
  scenario exists. The evaluator additionally logs a line (not a reject) when
  a plan's declared `feasibility` disagrees with its own actual pass/fail
  verdict.

Not free for existing producers, unlike most entries below: robust-rail-solver
and robust-rail-planner currently only ever produce the embedded-reversal
shape (they fold a reversal into a `Move`'s resource list rather than
emitting a separate action), so both need to start emitting `Setback` before
adopting `schemaVersion: 2`. The version gate exists specifically so this can
happen on each producer's own timeline: nothing currently emitted anywhere
regresses, since it all declares `schemaVersion: 1` today, and each producer
opts into the stricter rule only once it bumps its own output to declare `2`.

No real producer has ever emitted `"Walking"` as a value (see
robust-rail-evaluator's `doc/known-issue-plan-type.md`), so the rename itself
carries no migration cost. `feasibility` defaulting to `Unknown` (rather than
being strictly required with no default) means the new fields carry no
migration cost either — the version bump exists for the *behavioral* change
(the reversal reject), not for either schema addition.

## Unversioned — 2026-08-21

`reversalDuration` (on `TrainUnitType`) and `canDepartFromAnyTrack` (on
outStanding trains) are dropped from the wire format entirely — not narrowed,
removed. Both were `Optional` fields carrying unresolved `# TODO`s since the
schema was first frozen. Traced every consumer across all three repos before
removing:

- `reversalDuration`: the solver's real computation
  (`ShuntTrain.ReversalDuration`) derives it from `BackNormTime` +
  `Carriages * BackAdditionTime`; the standalone wire field was declared on
  the interchange DTO but never read by anything.
- `canDepartFromAnyTrack`: the generator only ever wrote it, TORS's C++
  serializer hardcoded `false` on output regardless of input and never read
  it back, and the solver's only former consumer (`Converter.cs`) had
  already been deleted.

**Not a version bump** — zero behavioral effect anywhere, same test as the
entries below: no consumer's runtime behavior changes, so `hip` and `tors`
need no code change and no rebuild.

Unlike the entries below, though, this one **is not free for the existing
fixture corpus**: `RailModel`'s `extra="forbid"` means every fixture that
still carries either key (even `null`-valued) now fails validation outright,
rather than silently continuing to pass. Every occurrence across
`scenario-planning-inputs` was `null` — neither field was ever set to a real
value — so removing the two keys is a mechanical, value-preserving edit, not
a data loss; downstream repos still need to make that edit before fixture
validation (and `extra="forbid"` deserialization generally) passes again.

## Unversioned — 2026-08-19

`Scenario.standingIndex` (in/outStanding trains) changed from
`Optional[float]` to `Optional[NonNegativeInt]`, and a new check rejects
ambiguous standing order: two or more standing units sharing a track must have
fully-specified, distinct `standingIndex` values (inStanding: required once
any one is set; outStanding: all-unset is fine, a mix of set/unset is not).
**Also deliberately not a version bump**, same reasoning shape as 2026-08-12:

- Nothing breaks. No fixture across `scenario-planning-inputs` has ever set a
  non-null `standingIndex` — checked directly, every occurrence in every
  committed `scenario_*.json`/`plan_*.json` is `null` — so the type narrowing
  changes nothing observable, and no track in the corpus has two or more
  standing units on it, so the new consistency check never fires today.
- The narrowing makes the schema honest about behaviour that already held one
  layer down: cTORS's `TrainGoal` already typed the field `const int`
  internally, silently truncating the wire double at construction. The
  evaluator needed no code change as a result; the solver did — its default
  for an absent index moved from `?? 0.0` to `?? 0` alongside the schema
  change, since it now reads an int rather than a double off the wire.

## Unversioned — 2026-08-12

`Location.trackParts`, `Plan.actions` and `Scenario.trainUnitTypes` became
required. **Deliberately not a version bump**, despite tightening the wire
format, and the reasoning is recorded here so it does not read as an oversight:

- Nothing breaks. All three fields were already emitted by every producer, in
  every one of the 143 fixtures in `scenario-planning-inputs` — and non-empty in
  every one, so even `minItems: 1` would have passed. The change makes existing
  practice enforceable rather than changing what anyone writes.
- A bump would have no mechanical effect anyway. Mismatch is warn-and-continue,
  so a consumer pinned to 1 reading a 2 logs a line and proceeds. The three
  repos would have paid the coordination cost of bumping
  `EXPECTED_SCHEMA_VERSION` together and bought nothing.

What this closes: `{}` validated as both a `Location` and a `Plan`, so a fixture
sweep reporting "N/N valid" was a weaker statement than it looked. It does
not close renamed or misspelled fields — `extra="forbid"` on `RailModel` already
rejects those — and it cannot make a *consumer* that reads a field with a silent
`.get(name, [])` default fail. What it does is let consumers drop that default
and index directly, which is where the actual protection lives.

`minItems` was considered and left off. It measures free today — no fixture has
an empty `trackParts`, `actions` or `trainUnitTypes` — but an empty plan is a
defensible representation of "nothing to do", and requiredness was the part
worth having.

## 1 — 2026-07-30

Initial version. `schemaVersion: 1` added to the top level of `Location`,
`Scenario`, and `Plan`.
