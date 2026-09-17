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

- **The `Setback` rename** (breaking): a new explicit `Setback` action,
  replacing a reversal that used to be silently embedded in a `Move`.
- **`Plan.feasibility`/`producer`/`cost`/`costDetails`** (purely additive): a
  producer's own declared verdict on whether its plan is feasible, plus
  free-text provenance/cost metadata.

Both originated from the same evaluator#12/#13 investigation and landed
together in this repo's own two-branch stack, so they move together here —
but the tool repos below don't necessarily need them at the same time, since
one is breaking and the other isn't. `robust-rail-generator` isn't part of
the rollout at all — it never produces or consumes a `Plan`, only
`Location`/`Scenario`.

Per-repo state, as of 2026-09-15:

- **evaluator**: two independent branches, both based on current `main`,
  *not* stacked on each other:
  - `fix/issue-13-wire-walking-to-setback` — the Setback-wiring fix, plus a
    companion regression it introduced and fixed in the same branch (a
    spurious "Parking is not allowed" rejection right before a Setback, see
    that branch tip's own commit message). Pushed, full suite green,
    **already merged into evaluator's own `edge`** (`6d5e00b`). **PR #23**
    open (correct direction this time — `head: fix/issue-13-wire-walking-to-setback`,
    `base: main`), CI/mergeability set, blocked only on required review.
    (Superseded PR #21, which had base/head swapped; closed 2026-09-15.)
  - `feat/plan-feasibility-cost` — parses `feasibility`/`producer`/`cost`/
    `costDetails` off an incoming plan and logs (never rejects) a warning
    when a plan's *declared* feasibility disagrees with the evaluator's own
    verdict, staying silent when the plan declares `Unknown`. This is real
    behavior on the exact path `run_evaluator.py` always uses
    (`plan_type == "Solver"` → `RunResult::CreateRunResult(pb_hip_plan, ...)`
    → `EvaluatePlan`), not a passive parse-and-ignore. **PR #22** is open
    (opened 2026-09-15) targeting `main`, CI green on both platforms,
    `mergeStateStatus: BLOCKED` purely on the required-review branch
    protection — nothing technical. **Not yet merged into evaluator's own
    `edge` either** — a dry-run merge against `origin/edge` shows no
    conflicts, so nothing blocks that but someone actually doing it.
- **solver**: a three-branch stack, `fix/rename-walking-to-setback` →
  `feat/plan-feasibility-cost` → `feat/emit-setback-actions`, each an
  ancestor of the next. All three are **already merged into solver's own
  `edge`** (`fbe9848`, 2026-09-13 00:52 CEST), and `hip:edge` has been
  rebuilt from that exact commit — confirmed directly from the live image's
  OCI labels (`2.1.0-edge+20260912.fbe9848`, built `2026-09-12T22:53:53Z`).
  Note solver doesn't actually populate real `Feasibility`/`Cost` values yet
  — its own commit says plainly "not wired up... nothing populates these
  from a real `SolutionCost`" — so every plan it emits today still declares
  `Unknown` with no cost. **PR #47** is open (lands all three pieces of the
  stack into `main` together, since `feat/emit-setback-actions` is the tip),
  blocked only on required review.
- **planner**: `feat/emit-setback-actions` (the Setback half) is still
  local, unpushed, unreviewed, based on `convert_to_tors_improvements`
  rather than `main` — hasn't landed anywhere, including planner's own
  `edge`. **Blocked on PR #32** ("Convert to tors improvements",
  `convert_to_tors_improvements` → `main`, currently `CHANGES_REQUESTED`;
  PR #33 is addressing that) landing first — and once it does,
  `feat/emit-setback-actions` needs to be **reworked onto `main`, not just
  rebased**, since it was built against a branch that won't be the current
  base anymore. **No `feat/plan-feasibility-cost` branch exists in planner
  at all.** Unconfirmed whether that's deliberate (planner produces plans
  too, as a producer, so could in principle declare its own
  feasibility/cost) or just not gotten to yet — worth asking rather than
  assuming either way.
- **this repo**: the `fix/rename-walking-to-setback` →
  `feat/plan-feasibility-cost` stack (general's schema source-of-truth
  changes backing all of the above) is pushed but **deliberately not yet
  merged into `main`** — sequenced to land after solver's and planner's
  Setback work, since that half is a breaking rename. The feasibility/cost
  half doesn't independently need that sequencing (see below), but it's
  bundled in the same branch stack here, so it moves together regardless.

### Verified: the forward-compatibility this sequencing relies on is implemented, not just documented

Checked directly in code, since solver's `edge` already ships a
schemaVersion-2 plan (including the new feasibility/cost fields) that
evaluator's `edge` doesn't yet expect: `robust-rail-evaluator`'s JSON plan
reader sets `ignore_unknown_fields = true`
(`cTORS/include/Utils.h:127-128`, exercised by `CompatibilityTest.cpp`, and
confirmed to be the code path `Plan.cpp:935` actually uses for `plan.json`),
and a schemaVersion mismatch only ever warns, never hard-rejects
(`warn_on_schema_version_mismatch`, covered by `SchemaVersionTest.cpp`;
evaluator's `EXPECTED_SCHEMA_VERSION` is still `1` on both `main` and
`edge`). This is why solver's producer-side change can safely ship ahead of
evaluator's consumer-side change — confirmed against real fixtures in the
2026-09-13 `edge` rerun in `roadmap-2.0.0.md`, not just inferred from the
schemaVersion policy table.

**What merging evaluator's `feat/plan-feasibility-cost` into `edge` would
still add**, given that: it would newly exercise the actual parse/round-trip
of these fields against solver's real `edge` output — do the optional
`producer`/`cost`/`costDetails` fields round-trip the way `has_producer()`
etc. expect, does the `Unknown` enum value map correctly end-to-end — which
evaluator's *current* `edge` can't provide any signal on, since it just
drops the fields via `ignore_unknown_fields`. What it would **not** yet
exercise is the interesting half of `WarnIfFeasibilityMismatch` — a producer
actually declaring `Feasible`/`Infeasible` and evaluator disagreeing —
because solver, as of 2026-09-15, does now wire real values through
(`eaf8d6a`, "Wire Plan.Feasibility/Cost/CostDetails/Producer to real
SolutionCost", bundled into PR #47 rather than a separate follow-up PR), but
that commit is still sitting in an unmerged PR, same as evaluator's own side.

### Priorities, in order

1. **Get solver PR #47 reviewed and merged into `main`** (lands its whole
   three-branch stack, including `feat/plan-feasibility-cost`, in one PR —
   now also including real `SolutionCost` wiring, `eaf8d6a`; blocked only on
   required review). Evaluator's PR #23 is open too, same state as #47.
   Planner is the long pole and has a real dependency now: **get PR #32
   fixed (PR #33) and merged first**, then rework `feat/emit-setback-actions`
   onto `main` — it can't just be pushed and rebased as-is.
2. **Get evaluator PR #22 reviewed and merged into `main`**, and separately
   merge `feat/plan-feasibility-cost` into evaluator's own `edge` — no
   technical blocker (no conflicts, CI green on both platforms), just needs
   doing. Worth prioritizing specifically for the round-trip integration
   coverage this unlocks against solver's real `edge` output (see above),
   even before solver populates real feasibility values.
3. **Once solver's and planner's Setback work land**, merge this repo's
   `fix/rename-walking-to-setback` + `feat/plan-feasibility-cost` stack into
   `main`, revert `fb45294` in `SCHEMA_CHANGELOG.md` (it deliberately
   reworded the "## 2" entry to "planned" so this revert could be
   mechanical) with the real landing date, and cut a new tag so
   `robust-rail-generator` can move its `robust-rail-general` pin off
   `v0.1.1` (which predates all of this).
4. **Investigate whether a reversal can reach a plan for free**, bypassing
   `Setback` (and its modelled cost) entirely — now filed as **solver#46**.
   Two suspected mechanisms in the solver, neither confirmed:
   `PlanGraph.ComputeRouting`'s `Access == Side.Both` branch picking a
   cheaper departure side with no check it's consistent with the train's
   actual arrival orientation, and a local-search neighbourhood move that
   could reach the same physical effect via Move+Wait+Move instead of a real
   Setback substitution. If real, this undermines the point of the whole
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
