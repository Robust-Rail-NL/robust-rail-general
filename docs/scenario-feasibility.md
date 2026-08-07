# Scenario feasibility

A configuration plus a seed produces a scenario, so feasibility is a property of
the *scenario*, not of the configuration. What a configuration has is a rate: how
often it yields a feasible scenario. Those rates are measured with
`sweep_seeds.py` and recorded here rather than in the configuration files,
because they are only true of a particular pipeline version and go stale the
moment a bug is fixed. The configuration files carry design intent instead, in
their `intent` block.

## Classification

| outcome | meaning |
|---|---|
| `feasible` | The solver produced a plan with no constraint violations and the evaluator confirmed it valid. |
| `infeasible` | The evaluator rejected the scenario before considering any plan — e.g. a train longer than the track it arrives on. Plan-independent, so this is a proof. |
| `unknown` | Everything else. A heuristic solver failing to find a valid plan is not evidence that none exists. |
| `generator` | The generator failed, so there is no scenario to judge. |

Only `infeasible` is ever a proof. `feasible` is as strong as the two tools
agreeing, which is why the assertions-enabled evaluator image matters: it turns
an internal invariant violation into a failure rather than a verdict computed
from corrupt state.

## Measured rates

Measured 2026-08-07 against locally built images at
generator `0597a6a`, solver `c913c91`, evaluator `e8c3c91`, solver
`MaxDuration: 15`.

| location | configuration | seeds | feasible | infeasible | unknown |
|---|---|---|---|---|---|
| KleineBinckhorst | `feasible_small` | 1–20 | 20 (100%) | 0 | 0 |
| KleineBinckhorst | `marginal_length` | 1–20 | 12 (60%) | 8 (40%) | 0 |
| KleineBinckhorst | `marginal_congestion` | 1–20 | 7 (35%) | 0 | 13 (65%) |

The two marginal configurations fail in quite different ways, and the
difference is the point.

`marginal_length` varies one thing: whether the drawn compositions fit the
255 m gateway. Its material is a single super type with two sub types of very
different length, so a two-unit train fits only if both draws are the shorter
one. Every failure is therefore a scenario-level rejection — a *proof*, with no
`unknown` verdicts at all. Note the rate was not predicted correctly
beforehand: a per-train fit probability of about 0.625 suggests roughly 39%
feasible for two trains, against 60% measured. The arithmetic was close enough
to pick sensible parameters and not close enough to trust, which is the reason
these rates are measured rather than derived.

`marginal_congestion` holds length constant and varies arrival pressure. It was
built expecting trains to be stranded on the gateway, and that is not what
happens: across seeds 1–20 not one failure was a gateway wait. The solver
instead overfills track 906b — a 255 m stub behind a buffer stop — and then
cannot extract the trains again ("exceeds the maximum length", "One side is
blocked by another train", "Both sides blocked"). That is the ordinary
difficulty of a dead-end parking track rather than a known bug, which makes the
fixture more useful than intended. Its failures are `unknown`, not proofs:
several may well be plannable by a better search.

An earlier run of the same sweep gave 19/20, the exception being seed 13:
`Shunting unit ShuntingUnit-7 should leave at time 9900`. That turned out not to
be a property of the scenario at all. The plan was correct — wait until 9720,
then a 180 s movement landing exactly on the 9900 departure — but the evaluator
stretched the wait to the next queued event, which was the departure itself, so
the movement ran 180 s past it. Fixed in evaluator `e8c3c91`; see the notes on
TORS's two operating modes in `roadmap-2.0.0.md`.

That is worth keeping in mind when reading any rate here: an `unknown` verdict
says the pipeline could not confirm a valid plan, which is not the same as the
scenario being hard.

## Fixed-scenario fixtures

These predate the seed-sweep work and are `trains_given` or single-seed, so they
have a verdict rather than a rate.

| scenario | outcome | note |
|---|---|---|
| `10t_random_42s_distribution1` | infeasible | arrival train 270.62 m > 255 m gateway (VIRM-4 + VIRM-6) |
| `10t_random_42s_distribution2` | infeasible | departure train 270.62 m > 255 m gateway |
| `48t_custom_larger-example` | infeasible | arrival train 324.12 m > 255 m gateway (2 × VIRM-6) |
| `6t_custom_example3` | unknown | train waits on the gateway; robust-rail-solver#13 |
| `7t_custom_example1` | unknown | the solver services train 2401 until 5734 against a 4800 horizon, so the plan does not leave it standing at the end. outStanding trains carry no deadline in the cost function, so over-running is free |
| `8t_custom_example2` | **feasible** | valid as of evaluator `2bbad58`; exercises StandIn, Arrive, Exit and StandOut in one plan |
| `30t_random_98s_test` | unknown | every train late both ways (`dd=30, da=29`); over-subscribed |
| `simple_service_location_4t_custom_late` | unknown | departure-time mismatch, likely infeasible by design |

The three `infeasible` verdicts are proofs: the arrival or departure track is
fixed by the scenario and the train does not fit on it, so no plan can help.

## Known blockers

Three defects still stop otherwise-reasonable scenarios from validating. All
three predate the 2.0.0 migration.

- **A train that waits on the gateway** is rejected, because the gateway forbids
  parking. It is not parked there by choice — it has arrived and not yet been
  routed into the yard — so modelling the wait as a `Wait` is arguably wrong.
  Tracked as robust-rail-solver#13. Blocks `6t_custom_example3`.
- **outStanding trains carry no deadline in the solver's cost function**, so a
  plan may schedule work past the end of the scenario at no cost and still be
  reported as unviolating. Blocks `7t_custom_example1`.
Departure times must still match exactly — the evaluator requires an `Exit` at
precisely the scheduled second — but that is no longer known to reject anything
it should not. The one case that looked like a strictness problem was the wait
bug above, so a tolerance would have papered over a defect while also starting
to accept genuinely late departures.

## Why nothing was feasible before 2026-08-07

Every movement in a replayed plan is built as a `MultiMove`, and
`legal_on_parking_track_rule` rejected any non-step movement whose destination
forbids parking. A departure's final movement lands on the gateway, which is
`parkingAllowed: false` because it is the connection to the main line. So on
KleineBinckhorst no plan could depart a train, and no plan could be valid — in
any evaluator release from v1.0.0 onwards, including the `tors:1.3.1` protobuf
baseline. `Location_SimpleService` marks every track `parkingAllowed: true`,
which is why it was never affected. Fixed in evaluator `4482fa2`.
