# Planner runs against the fixtures

We ran `run_planner.py` over the KleineBinckhorst fixtures.  Here are the
outcomes:

| outcome | feasible (39) | infeasible (8) | where it fails |
|---|---|---|---|
| plan JSON written | 8 | 0 | — |
| ENHSP reports `Unsolvable Problem` | 22 | 1 | AIBR preprocessing, before search |
| converter rejects an action | 9 | 7 | `convert_to_tors.py:1032`, after ENHSP solved |

Taking ENHSP's own verdict rather than the end-to-end result — conversion is a
separate downstream stage — the headline is:

| fixture set | n | ENHSP solved | ENHSP unsolvable |
|---|---|---|---|
| known feasible | 39 | 17 (44%) | 22 (56%) |
| known infeasible | 8 | 7 (88%) | 1 (12%) |

**An `Unsolvable` verdict carries no signal.** ENHSP is in fact more likely to
return a plan for a provably infeasible instance than for a feasible one, so the
verdict is mildly anti-correlated with the truth.

By configuration, on the feasible pass:

| configuration | runs | success | unsolvable | converter |
|---|---|---|---|---|
| `feasible_small` | 20 | 1 | 16 | 3 |
| `marginal_length` | 12 | 7 | 0 | 5 |
| `marginal_congestion` | 7 | 0 | 6 | 1 |

## Failure type 1 — 22 false unsolvable verdicts

All 22 fail identically, with `Problem Detected as Unsolvable by AIBR during
preprocessing`. There are no timeouts, no crashes and no exhausted searches: the
numeric relaxation declares the problem unsolvable before search begins.

Every one of these 22 instances has a valid plan from the existing solver,
confirmed by the evaluator. A relaxation that proves a feasible instance
unsolvable is unsound, so these are **modelling bugs in the PDDL or its
grounding, not planner capacity limits**.

## Failure type 2 — 16 converter rejections

All 16, across both passes, name the same unmodelled action:

```
(compiled_adopt_composition su_train2 su_request6 sein70)
```

The number of unrecognised actions in each run equals the number of coupled
two-unit arrivals in that scenario exactly — 1 for `feasible_small_s01`, 2 for
`marginal_length_s13`, 5 for `marginal_congestion_s08`. This is a single missing
pattern rather than sixteen separate gaps. The guard behaved correctly; without
it these plans would have been silently truncated.

## Instance size is not the driver — composition arity is

Sizes span 2–14 arrivals, 2–23 units and grounded `|F|` from 24 to 13442, and
that axis does not predict the outcome:

- The largest instance ENHSP solved is `marginal_congestion_s08` — 14 arrivals,
  19 units, `|F|`=5133. It failed only in conversion.
- The smallest instance declared unsolvable is `feasible_small_s03` — 4
  arrivals, 6 units, `|F|`=525.

What does predict the outcome, on the feasible pass, is whether any train
arrives or departs as a coupled pair:

| coupled arrivals | outcome |
|---|---|
| 0 | success — 8 of 8, no exceptions |
| 1 or more | failure — 31 of 31 |

All 8 successes are exactly the instances in which every arrival and departure
is a single unit. The smallest failing instance, `marginal_length_s06` at 2
arrivals and 3 units, is smaller than several successes. The planner handles no
composition at all: the moment two units are coupled it breaks, either as a
converter gap when ENHSP solves or as a false unsolvable when it does not.

This also explains the per-configuration spread above — it tracks how often each
configuration draws coupled trains, not how large its scenarios are. Note that
all 8 infeasible fixtures contain coupled arrivals, so that pass cannot test
this axis independently.

## The negative control: infeasible scenarios are planned anyway

All 8 `infeasible` fixtures are infeasible for the same plain, plan-independent
reason — an arriving train is longer than the track it arrives on:

| instance | longest arrival | gateway `906a` (track 15) | fits |
|---|---|---|---|
| `marginal_length_s16` | 324.12 m | 255 m | no |
| the other 7 | 270.62 m | 255 m | no |

This is exactly the `marginal_length` design intent: a two-unit VIRM train fits
only if both draws are the shorter 108.56 m variant. **The PDDL model has no
such constraint**, so it plans straight through a train that physically cannot
arrive. This is the same missing numeric reasoning implicated in the false
negatives above, seen from the other side.

## The one correct rejection is right by accident

`marginal_length_s05` was declared unsolvable, but not for being too long. It
carries the `|X|`=21 anomaly signature described below — the same mechanism that
rejects feasible instances. Its structural twins violate the identical length
bound and were all solved:

| instance | coupled arrivals | first arrival | `\|X\|` | ENHSP |
|---|---|---|---|---|
| `marginal_length_s05` | 2 (VIRM6+4, VIRM4+4) | 217.12 m | **21** | unsolvable |
| `marginal_length_s11` | 2 (VIRM4+4, VIRM6+4) | 270.62 m | 8 | solved |
| s09, s12, s16, s17 | 2 | ≥ 270.62 m | 8 | solved |

s05 and s11 hold the same two compositions and differ essentially in which
arrival slot carries the mixed pair. One grounds 21 numeric fluents and is
rejected; the other grounds 8 and is solved.

That makes **s05 versus s11 a minimal reproducer** for the grounding bug: two
near-identical instances, opposite verdicts, no structural difference to explain
it. Two obvious candidate explanations were tested and ruled out — distinct pair
types (both have exactly one) and "the first arrival fits" (`s04` and `s10` fit
and are solved normally).

## The `|X|` signature

Across all 47 runs, the grounded numeric fluent count `|X|` separates the two
ENHSP verdicts perfectly:

- `|X| = 4 + 2 × (coupled arrivals)` — ENHSP solves it. 24 of 24.
- `|X|` above that — ENHSP declares it unsolvable. 23 of 23.

No exceptions in either direction, on feasible and infeasible instances alike.
The unsolvable instances therefore ground a *different* set of numeric fluents,
not merely more of the same: `feasible_small_s03` grounds 21 where the formula
predicts 8. Whatever causes those extra fluents to ground is the false-unsolvable
bug, and the s05/s11 pair shows the trigger lies in the data values rather than
in the coupling structure.

One related observation: `Numeric Error for Complex Condition Activated` appears
in every run ENHSP solved, so its numeric condition handling is degrading even
on the successes. The 8 plans that were written deserve evaluator validation
before being trusted.

## What to fix first

**Do not fix the converter first.** All 7 solved-but-infeasible runs died at
`convert_to_tors.py:1032`, and that gap is the only reason no invalid plan
reached disk. Adding the `compiled_adopt_composition` pattern in isolation would
move the pipeline from failing loudly to emitting TORS plans for physically
impossible scenarios.

Suggested order:

1. Model the arrival-track length constraint, so infeasible scenarios are
   rejected for the right reason.
2. Fix the false-unsolvable grounding bug, using `marginal_length_s05` versus
   `s11` as the reproducer.
3. Only then add the converter pattern — or land it behind an evaluator
   validation gate on every emitted plan.
