# What does the order of train units mean? A convention for the whole pipeline

Date: 2026-11-24. Status: investigation, no code changed. Sources: the five repos (solver at v2.3.0, evaluator at v2.4.0, planner at v0.6.0, generator v2.5.0, visualizer and this repo as checked out), Roel van den Broek's thesis [1] and paper [2] (see References), and the results of Issa's grid experiment.

**Decision, 2026-11-24 (Léon): head-first** (index 0 = the head), for arriving and departing trains. Standing trains
(`inStanding`, `outStanding`) stay along the track, starting at the end nearest the A side of the track they stand on. The
schema descriptions say this, and a file declares it with `schemaVersion` 3 (decided 2026-11-27; see `SCHEMA_CHANGELOG.md`):
a scenario of version 3 or later is head-first, an older one is read along the track as before, and the evaluator reads
the convention from the scenario's version. Scenario fixtures and the generator were migrated (the fixtures that were
migrated, and the ones re-swept, declare 3). The evaluator is done; the planner (robust-rail-planner#65) and the solver
(#84, #87) are still to do. The text below is the investigation that led to the decision, written before it, so
"Proposal" reads as a proposal.

## Why this came up

In the grid experiment the solver fails 14 of 17 scenarios in which a train arrives as, say, [4,6] and has to depart as [6,4] (symbolic-rail solves all 17, ENHSP 11). The planners and the evaluator accept the reversed order; the solver does not. An expert at NS has since answered that a mirrored departure order is not allowed. Looking for the cause showed that the components do not share one definition of what the order of a unit list means.

## The question

A list of units (`in[].members`, `out[].trainUnits`, a plan's `memberIDs`) can be read in two ways:

- **Yard-centric:** from one side of a track to the other (A to B, "left to right"). Reversing a train (a saw move) changes which end is the head, not the order along the track.
- **Train-centric:** from the head of the train. Reversing a train flips the order read from the head, and the head's position along the track follows from the direction of travel.

## What each component does today

| Component | Index 0 of a unit list | Evidence |
|---|---|---|
| Thesis, paper | yard-centric: "from left to right … in the train on the service site"; the head is the left-most unit only when the train moves to the left | thesis p.24, paper p.13; saw move: control passes to the tail, thesis p.18 |
| Schema, docs | undefined | no description on `members` (`robust_rail_models/scenario.py:114`), `trainUnits` (`:141`), `memberIDs` (`schema/schema_plan.json:147-151`) |
| Generator | no intended direction; keeps the unit order inside a train (LIFO reverses the order of trains only; random shuffles units) | `random_generator.py:210-235`, `:617-621` |
| Solver | train-centric: index 0 is the head (the unit that led the train in); a reversal flips the leader by parity, the list stays fixed | `ProblemInstance.cs:716-720, 837-860`; `PlanGraph.cs` ~340-381 (`UnitZeroLeads`, `Units0Side`); output `PlanGraph.cs:2205-2211` |
| Planner | train-centric: index 0 is the head (`front_of` on the first unit); flips the unit rank when a train enters and leaves through the same gateway | `convert_to_pddl/convert.py:2185-2217`, `:240-270` |
| Evaluator | train-centric, but the JSON list is read tail-first: it reverses every list on input and treats the last element as the front train; the head is tracked separately in `frontTrain` | `cTORS/src/vehicles/ShuntingUnit.cpp:6-33`; `State.h:239`; `State.cpp:366-375` |
| Visualizer | yard-centric when drawing: units along the track from the A end, from its own simulation | `visualize_plan.py:405-413` |

## Inconsistencies found

1. **The JSON list is read in opposite directions.** The solver and the planner take index 0 as the head; the evaluator takes the last element as the head (on `custom_1_random_4`, JSON `[VIRM-4, VIRM-6]` is stored as `((1,VIRM-6)(0,VIRM-4))` with head id 1). Because the evaluator reverses arrivals and departures alike, the relation between the arrival and the departure list is the same everywhere, and the exit check does not notice. The absolute meaning matters wherever the head's identity matters: placement on a track at arrival, split sides, standing trains. Whether that explains some of the roughly 20 combine-direction rejections or the 62 plans the solver considers feasible and the evaluator rejects has not been tested.
2. **The evaluator ignores its own head at Exit.** `MatchesShuntingUnit` (`ShuntingUnit.cpp:104-125`) accepts a departing unit if it matches the request read from either end, and compares the plan's declared list, not the physical state. This rule is from the original TORS (2021).
3. **The solver contradicts itself.** Its orientation bookkeeping is head-based, but its matching builds a part only from a run of increasing indexes (`BipartiteGraph.cs:394`), as if the order were fixed along the track. By its own convention, [4,6] arriving and [6,4] departing through the same gateway is a single `Reverse`, with no split. It splits and recombines instead (`custom_1_random_4`: Move, Split, Combine, `Reverse` 524 s, Move, Exit).
4. **The planner models a flip it does not write.** `_unit_source_positions` reverses the rank for a train that leaves through the same gateway, but `_members_for` (`convert_to_tors.py:777-783`) writes `memberIDs` in the unflipped arrival order, and no `Reverse` is emitted between the two Moves (`:596-620` counts reversals only inside one Move). Its mirror acceptance (commit `7119a90`, `convert.py:2398`) leans on the evaluator's symmetric exit check.
5. **The evaluator accepts a turnaround without a `Reverse`.** In the planner's plan for `custom_1_random_4` the unit goes to track 52 and back with no `Setback`, and `frontTrain` stays unit 1 throughout (`MoveAction::Start:33` flips it only for a unit in neutral that leaves by the side it came from). At Exit the head-first order is [VIRM-6, VIRM-4], while the request wants VIRM-4 at the head. A head-based exit check would reject this plan; a `Reverse` (which switches the head) would make it pass.
6. **Nothing is documented.** Neither the schema nor the READMEs state a convention.

## Proposal

Adopt the train-centric convention, with index 0 as the head:

- It is what the solver's and the planner's bookkeeping already assume, and it is how the question was put to the NS expert ("SNG-3 vooraan").
- It makes a turnaround meaningful: a real `Reverse` flips the order read from the head, so [4,6] to [6,4] through one gateway costs one reversal, not a split and a combine; mirroring without a reversal is not allowed. The flip side (see below): written head-first on both sides, the same order through one gateway then needs two reversals or a split.
- It departs on purpose from the thesis, which defines the list yard-centrically. The schema text should say so, and why. The thesis model can still be expressed: its "left to right" is a rendering of the same state.

Proposed text for the schema (`members`, `trainUnits`, `memberIDs`), to be refined:

> The order of the units of a train, from the head of the train to its tail. For an arriving train the head is the unit that leads the train into the yard; for a departing train it is the unit that leads the train out. Reversing the direction of a train (a `Reverse`) swaps which end is the head, so it reverses the order as read from the head. Units that are not coupled keep no order.

`standingIndex` stays as a track-end rule for standing trains; its relation to the head needs one more sentence once the evaluator's input reading is settled.

## Both readings are encodings; the convention also decides what existing scenarios require

Head-first and along-the-track are two ways of writing down the same physical facts: the units of an arriving train, and the units a departing train must have. Once one convention is fixed for both lists, converting between them is mechanical, and the physics is the same under either. The physical fact that matters is this: a train that enters the yard through the single gateway and leaves through it again has to turn around at some point (a `Reverse`), which swaps its head. The order of its units along the track does not change, so the order read from the head does.

Conversion rule (derived, not yet checked against Kleine Binckhorst): on arrival the head of the train is at the deep end of the track, and on departure it is at the end next to the gateway, so the head is at opposite ends of the track on arrival and on departure. A list written along the track (A to B) is therefore head-first for one of the two trains and tail-first for the other, and converting an along-the-track scenario to head-first means reversing exactly one of its two lists. Which one depends on which end of the track is the gateway side.

What is not a pure renaming is what the *existing* files mean. The same JSON asks for different things under the two conventions:

- Read along the track, a train that arrives as [A,B] and has to depart as [A,B] needs no reordering; [B,A] does (the thesis and paper, p.49 and p.35).
- Read head-first on both sides, [A,B] to [A,B] needs a turnaround of the right parity or a split and recombine, and [A,B] to [B,A] is one turnaround.

The generator copies the arrival list into the departure list for FIFO and LIFO (LIFO reverses only the order of the trains), so identical lists are very common in the data, and the solver currently treats them as free. Under a head-first reading the same files become harder scenarios. So the decision comes with a second one: re-interpret the existing scenarios under the new convention (and rerun whatever was measured on them), or migrate them (reverse one of the two lists, in the files and in the generator) so that the physical requirement they were meant to express stays the same. For that, the generator's intent for each matching mode has to be checked.

The expert's answer (a mirrored departure order is not allowed, "SNG-3 vooraan") only says that a departing train has to have the requested units at the front as it leaves; it does not choose a convention.

## What each change would be

1. **Schema and docs (small).** The text above in `scenario.py`, `plan.py`, the regenerated schemas, `unified-schema-design.md`, `SCHEMA_CHANGELOG.md` (an entry: clarification, with the evaluator behaviour change; whether it needs a `schemaVersion` bump is a decision), the generator's configuration guide and README, the visualizer README.
2. **Evaluator (medium).** A new directional function used only by the exit rule (`out_correct_order_rule.cpp:13`) that compares `State::GetTrainUnitsInOrder` (head-first) with the request. `MatchesShuntingUnit` must stay symmetric for its other callers (`HasShuntingUnit`, `GetMatchingShuntingUnit` at `State.cpp:239, 258`, `Scenario.cpp:115/125`; `CombineAction::Start` finds the combined unit through it). Settle the input reading (`ReverseTrainOrder`) so index 0 is the head. Decide whether a back-and-forth by two Moves without `Reverse` is rejected or counted as a setback (a `Reverse` should be required when there is no wait, or too short a wait, between the two Moves). Tests: same order accepted, reversed rejected, after `Reverse`, after Split plus Combine, Move-back without `Reverse`. Suggested rollout: first as a warning, count the plans it flags, then a hard rule.
3. **Planner (medium to large).** Emit a `Reverse` for the turnaround, write `memberIDs` in the flipped order, remove the mirror acceptance (`7119a90`, five lines). The planner's PDDL has no head orientation and no `Reverse` action, so the proper fix touches the model, `convert.py` and `convert_to_tors.py`, plus a new measurement run. Expect symbolic-rail and ENHSP to lose some reverse-only scenarios they now solve until it is done.
4. **Solver (small to medium, but see the section on existing scenarios above).** Make the matching depend on the parity of reversals: accept a run in reverse order when the number of reversals is odd, so no split is planned, and check that a run in the same order with an even number is only free when that parity really is even; change the part construction (`BipartiteGraph.cs:392-413`), the matching cost (`:261-279`), `Part`/`TrainMatching` grouping, `MatchingSwapMove` and `SimpleHeuristic`, with a test beside `Tests/TestSameTrackDeparture.cs`. Separately, nothing checks the physical order at departure and `UpdateDepartureOrder` is dead code (to be filed as a separate issue).
5. **Generator, visualizer (documentation).** State the convention; the visualizer's A-to-B drawing is fine as a rendering.

## To verify first

- **Arrival placement:** do the solver and the evaluator place the same unit deepest in the track on arrival, given that they read index 0 in opposite directions? A test with a one-train scenario and a split would show it.
- **Impact of the exit check:** with the full grid data from DAIC (only part of it was available when this was written), count the valid plans with a mirror-only Exit. The solver's own valid plans have none (149 of 345 examined); of the planner plans only 2 each were available, both mirror-only.
- **The implicit flip:** when exactly `MoveAction::Start` flips `frontTrain`, and whether it is intended.

## Not established

How the original TORS documentation defined the order (not checked); whether the physical order at departure is right in solver plans (guarded only indirectly, and the evaluator cannot tell); whether other parts of the solver assume a fixed direction; the cause of the evaluator's five "unexpected error" crashes (`State.cpp:368`, `State.h:178`); how often each tool's plans would change under the proposal.

## References

Page numbers in this document ("thesis p.24", "paper p.13", ...) refer to the thesis PDF and to the arXiv-style preprint of the paper dated 20 January 2021; the published version has different pagination.

1. R. W. van den Broek. *Train Shunting and Service Scheduling: an integrated local search approach.* Master's thesis, Utrecht University, August 2016. https://studenttheses.uu.nl/handle/20.500.12932/24118
2. R. van den Broek, H. Hoogeveen, M. van den Akker and B. Huisman. A Local Search Algorithm for Train Unit Shunting with Service Scheduling. *Transportation Science*, 2022. https://doi.org/10.1287/trsc.2021.1090
