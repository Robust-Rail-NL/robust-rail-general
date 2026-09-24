# Roadmap: loose ends, priorities, outlook

This is the living cross-repo roadmap: what's in flight right now, what to
pick up next, and what's worth planning for further out. Unlike
[`roadmap-2.0.0.md`](roadmap-2.0.0.md) — which is scoped to the 2.0.0 release
and now holds mostly historical/reference detail (the known-issues table,
resolved decisions, the rc-by-rc verification log) — this file is meant to
stay current and gets rewritten as priorities shift, rather than accreting a
narrative log. When something here is fully landed, delete it rather than
striking it through; `git log -p docs/roadmap.md` is the record.

See [CONTRIBUTING.md](../CONTRIBUTING.md) for this repo's own `main`/`edge`
branch model, and the repo-branch-awareness table in
[`CLAUDE.md`](../CLAUDE.md) for what `main`/`edge` mean in each of the other
four repos — several items below depend on that model (a fix living on a
feature branch, merged into a repo's `edge`, with its `main` PR still open).

---

## Right now: the schema v2 rollout

evaluator#12 (task-duration global sum bug) and evaluator#13 (saw movement
flips a train's tracked orientation) triggered a schema v2 change — bundled
under one shared version bump, but actually **two independent features**:

- **The `Reverse` rename** (breaking): a new explicit `Reverse` action,
  replacing a reversal that used to be silently embedded in a `Move`. (Named
  `Setback` until partway through this rollout; renamed for readability —
  see `SCHEMA_CHANGELOG.md`.)
- **`Plan.feasibility`/`origin`/`cost`/`costDetails`** (purely additive): a
  plan's declared verdict on whether it's feasible, plus free-text
  provenance/cost metadata. (`origin` was named `producer` until the same
  point, for the same reason.)

Both originated from the same evaluator#12/#13 investigation and landed
together in this repo's own two-branch stack, so they move together here —
but the tool repos below don't necessarily need them at the same time, since
one is breaking and the other isn't. `robust-rail-generator` isn't part of
the rollout at all — it never produces or consumes a `Plan`, only
`Location`/`Scenario`.

Per-repo state, as of 2026-09-24 (the rename settled on `Reverse`/`origin`
rather than `Setback`/`producer` along the way — `producer` collided with
this same doc's use of "producer" as a schema-versioning role term):

- **this repo**: the `fix/rename-walking-to-reverse` → `feat/plan-feasibility-cost`
  stack (general's schema source-of-truth changes backing all of the below)
  **merged into `main`** (PRs #15, #16) and already carried into `edge`
  (`main` merged into `edge` same day) — no longer sequenced behind
  anything, since solver and evaluator's own Reverse work landed the same
  day (see below).
- **solver**: the three-branch stack (retitled along the way, tip
  `feat/emit-reverse-actions`) **merged into `main`** via **PR #47**
  (2026-09-24), and `main` merged into `edge` the same day. Unlike the
  2026-09-15 snapshot of this doc, this now includes real `Feasibility`/
  `Cost`/`Origin` wiring off `SolutionCost` (`eaf8d6a`, bundled into the same
  PR) — solver's plans no longer all declare `Unknown` with no cost. `edge`
  image already rebuilt from this (GHCR `edge` tag pushed 2026-09-24T19:45Z).
  **Landed on `main`/`edge`, but not yet released** — `stable` is still
  pinned to `v2.1.0`, which predates PR #47; no new tag cut yet.
- **evaluator**: two independent tracks, no longer stacked:
  - The Reverse-wiring fix, **PR #23** (`fix/issue-13-wire-walking-to-reverse`)
    — **merged into `main`** 2026-09-24, having already been on evaluator's
    own `edge` before that.
  - `feat/plan-feasibility-cost`, **PR #22** (parses `feasibility`/`origin`/
    `cost`/`costDetails`) — **still open**, blocked only on required review
    (CI green on both platforms); its content is already merged into
    evaluator's own `edge` directly (`d285bd1`), so nothing blocks the
    round-trip coverage this unlocks. **Someone is actively iterating on
    this branch right now** (a live worktree, most recent commit reworking
    `producer` mentions in comments/docs to `origin`) — check before
    touching it.
- **planner**: still the long pole. Its former blocker — PR #32
  (`convert_to_tors_improvements` → `main`) needing rework — is resolved:
  both PR #32 and its follow-up PR #33 merged into `main` back on
  2026-09-17. But `feat/emit-setback-actions` itself is still local-only,
  unpushed, and based on a `main` commit that's since fallen well behind —
  it still needs the rework onto current `main` flagged before, not just a
  rebase. **No `feat/plan-feasibility-cost` branch exists in planner at
  all**, still unconfirmed whether deliberate.

### Verified (2026-09-15): the forward-compatibility this sequencing relies on is implemented, not just documented

Checked directly in code, back when solver's `edge` shipped a schemaVersion-2
plan that evaluator's `edge` didn't yet expect: `robust-rail-evaluator`'s
JSON plan reader sets `ignore_unknown_fields = true`
(`cTORS/include/Utils.h:127-128`, exercised by `CompatibilityTest.cpp`, and
confirmed to be the code path `Plan.cpp:935` actually uses for `plan.json`),
and a schemaVersion mismatch only ever warns, never hard-rejects
(`warn_on_schema_version_mismatch`, covered by `SchemaVersionTest.cpp`).
This is why solver's producer-side change could safely ship ahead of
evaluator's consumer-side change — confirmed against real fixtures in the
2026-09-13 `edge` rerun in `roadmap-2.0.0.md`, not just inferred from the
schemaVersion policy table.

Now that both solver and evaluator have `Reverse`/schemaVersion-2 on `main`
(see above), the same lean-on-forward-compatibility logic is what lets
**planner** stay behind without blocking anyone: planner still emits
`schemaVersion: 1` plans with the old embedded-reversal shape, and nothing
above rejects that — it's exactly the mismatch path just verified, just with
the lagging side now being planner instead of evaluator. Worth re-confirming
against real planner fixtures once its rework starts, rather than assuming
the solver/evaluator verification generalizes unchecked.

### Priorities, in order

1. **Get evaluator PR #22 reviewed and merged into `main`.** No technical
   blocker (CI green on both platforms, no conflicts) — its content is
   already on evaluator's own `edge`, so this is purely the review-and-merge
   step. Someone is actively iterating on the branch right now (see above);
   coordinate rather than duplicating that work.
2. **Rework planner's `feat/emit-setback-actions` onto current `main`** (a
   rework, not a rebase — see above) now that its former blocker (PR #32/#33)
   has been merged for over a week. This is the actual long pole left in the
   rollout. Also worth asking directly: should planner get its own
   `feat/plan-feasibility-cost`-equivalent branch (it produces plans too, so
   could declare its own feasibility/cost), or is that deliberately out of
   scope for it?
3. **Cut a new `robust-rail-general` tag** now that this repo's stack has
   landed, so `robust-rail-generator` can move its pin off `v0.1.1` (which
   predates all of this).
4. **Investigate whether a reversal can reach a plan for free**, bypassing
   `Reverse` (and its modelled cost) entirely — now filed as **solver#46**.
   Two suspected mechanisms in the solver, neither confirmed:
   `PlanGraph.ComputeRouting`'s `Access == Side.Both` branch picking a
   cheaper departure side with no check it's consistent with the train's
   actual arrival orientation, and a local-search neighbourhood move that
   could reach the same physical effect via Move+Wait+Move instead of a real
   `Reverse` substitution. If real, this undermines the point of the whole
   rollout — the solver could silently prefer the unrealistic-but-free
   reversal over the correctly-priced one. Scoped to the solver's routing
   graph and local search; suitable for its own session.
5. **Post the drafted evaluator#12 PR** once reviewed
   (`__scratch/issue12_pr_draft.md` in the evaluator repo). evaluator#13's
   reporter reply is already posted.

---

## Cross-repo process

- **`edge-main-divergence-check`** — a weekly scheduled Claude Code cloud
  routine (Mondays 06:00 UTC) checking whether `edge` and `main` have
  diverged in a way suggesting the same fix was written twice, across all
  four repos with an `edge` branch. Read-only; run log at
  `https://claude.ai/code/routines/trig_01QF8sv8BLkJPXwxwXVHSkXq`.
- The `stable`/`edge` channel model itself (image channel for solver,
  evaluator, planner; branch channel for this repo) is still fairly new
  (started 2026-08-26/27) and isn't written up anywhere longer-form than the
  git history and each repo's own `CONTRIBUTING.md`. Worth a proper doc if it
  grows more channels or picks up more repos.

---

## Longer-term outlook

- **solver#43 — `PlanGraph.ComputeTime` threads one global clock across all
  trains.** It computes every move's start/end by walking the plan's single
  interleaved `NextMove` list while carrying one shared scalar `time`
  forward, so a move's earliest start ends up floored by whatever move
  happens to sit next to it in that list — even a different train, on a
  different track, with no real relationship to it — not just by its actual
  causal predecessor. Confirmed at the code level (no resource-identity
  check exists) and empirically (a real `multiple_instanding` repro shows a
  4199-second forced delay from an unrelated move). Suspected strong
  candidate for solver#23's six-departures-at-identical-time-5300 symptom,
  though the exact bunching hasn't been reproduced from that historical plan
  yet. Proposed direction: a genuine per-resource (at minimum per-track,
  ideally per-train) notion of time — a Simple Temporal Network would give
  this precisely, and would also subsume solver#42 (`Crossings` conflicts
  priced as cost rather than enforced as a constraint) by turning a
  blocking-unit dependency into a real edge instead of a post-hoc cost tally.
  Branch started in solver (`issue-43-plangraph-time-model`, off `main`);
  the actual investigation is being picked up in its own focused Claude
  Code session, not folded into cross-repo roadmap work.
- **A focused session on TORS's own search mode.** TORS doesn't only replay
  and evaluate a plan — it can also generate one itself, which looks to be
  what it was originally built for, with replay added later. This matters
  beyond curiosity: nearly every evaluator bug found on 2026-08-07 was a
  search-mode primitive behaving wrongly under replay, not a bug in its own
  right (`legal_on_parking_track_rule`, `Wait`'s "run until next event"
  semantics, `ArriveActionGenerator`'s hardcoded zero duration, and
  `out_correct_time_rule`'s exact-time requirement all fit this pattern —
  see `roadmap-2.0.0.md`'s known-issues section for the concrete bugs). A
  survey of where else the two modes share a primitive whose contract only
  holds in one of them would probably predict the next round of bugs rather
  than waiting to trip over them one at a time.
- **Package `robust_rail_models` properly.** The interchange models moved
  here from the generator (PRs #9/#17, 2026-09-02), but this repo isn't
  packaged as an installable dependency yet, so the generator still pins a
  git tag by hand. Needs a pin/lockfile discipline decision (matching the
  Docker-tag pinning already in force for the solver/evaluator images) and a
  choice of distribution mechanism — git dependency vs. a published package.
- **Planner output isn't a valid solution yet, for two known reasons**: the
  evaluator rejects plans on facility availability the PDDL model can't see
  (`convert_to_tors` doesn't read `timeWindow`), and `convert_to_tors` stops
  emitting actions partway through a plan (no trailing `Exit`), held as a
  strict `xfail`. Separately, **planner and solver output collide** — both
  write `plans/plan_<suffix>.json`, `run_evaluator.py` globs
  `plans/plan_*.json`, and `run_pipeline.py` currently just refuses to run
  both rather than distinguishing them. Comparing planner and solver output
  on the same scenario needs an actual design (separate output directories,
  or a filename convention `run_evaluator.py` and evaluation naming both
  understand) — not just a policy of never running both.
- **Decide the `--plan_type Evaluator` question.** Three separate decisions,
  laid out in full in `roadmap-2.0.0.md`'s "Open decisions" section: is the
  self-contained `Run` format wanted at all; if so, does it need a *reader*
  (only the reader is `--plan_type Evaluator`, and only the reader blocks
  several legacy-format cleanups); and if wanted in full, it needs a fixture
  and a test, which it has never had. Nobody on hand has actually used this
  mode — whoever knows why the Python bindings exist should decide.
- **Retire the `legacy` `--version` choice outright.** Stopped working once
  Phase 1 moved these scripts to the unified format unconditionally; still
  just documented as a dead end rather than removed.
- **Solver cleanup, not urgent**: `dotnet build` isn't warnings-as-errors —
  two nullable warnings live in `Initial/SimpleHeuristic.cs`. (The
  `ServiceSiteScheduling.NoProto` → `Interchange` rename that used to be
  listed alongside this is done — `267181e` on `main`.)

---

## Reference

`roadmap-2.0.0.md` still holds two things worth knowing where to find rather
than duplicating here:

- **"Reference: decisions still in force"** — the wire-format decisions
  (`schemaVersion` semantics, `Resource` shape, type identity, and so on)
  that constrain anything built on the schema, kept there because that's
  where they've been since 2.0.0 and nothing here has revisited them.
- **The known-issues table** — every currently open solver/evaluator defect
  with its effect and status. evaluator#18 (in that table) was fixed and
  merged to both `main` and `edge` 2026-09-13 (`aa499be`); both previously-
  blocked fixtures (`6t_custom_example3`, `8t_custom_example2`) were
  re-verified valid under `edge` the same day — see that table's own entry
  and the "evaluator#18 fixed" section right after it for the full
  re-verification. Item 4 above (solver#46, the free-reversal question) is
  also an entry in that table; check it before relying on a status claimed
  here, since it's meant to be re-verified more often than this file is
  rewritten.
