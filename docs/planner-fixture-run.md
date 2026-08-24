# Planner runs against the fixtures

We ran `run_planner.py` over the KleineBinckhorst fixtures, against the
`planning-approach` image built from `fix-fixture-converter-bugs` (run of
2026-08-14). All 39 `feasible` and 8 `infeasible` fixtures were symlinked into
`scenarios/` and run. Here are the outcomes:

| | n | ENHSP solved | ENHSP unsolvable | other |
|---|---|---|---|---|
| known feasible | 39 | 38 | 0 | 1 (out of memory) |
| known infeasible | 8 | 0 | 8 | 0 |

**Zero misclassifications in either direction.** `PLAN IS VALID` appears on
exactly the 38 solved feasible runs and on none of the infeasible ones. Of the 8
rejections, 5 come from AIBR preprocessing and 3 after search.

Against the previous image this is a large move on both axes:

| | before (2026-08-12) | now |
|---|---|---|
| feasible instances solved | 17/39 (44%) | 38/39 (97%) |
| infeasible instances solved | 7/8 (88%) | 0/8 (0%) |

## The length constraint is now modelled

The previous image had no notion of whether an arriving train fits the track it
arrives on, so it planned straight through provably infeasible scenarios. It now
discriminates exactly on the 255 m gateway (`906a`, track 15):

| max arrival length | fits? | instances | verdict |
|---|---|---|---|
| 108.56–217.12 m | yes | 12 feasible | all solved |
| 270.62–324.12 m | no | 8 infeasible | all unsolvable |

`marginal_length` is a clean natural experiment for this, because length is the
only thing it varies. `marginal_length_s13` (two coupled VIRM pairs, 217.12 m)
solves, while `s09` — same structure, 270.62 m — is rejected.

## Coupled compositions are now modelled

The previous image failed on every instance containing a multi-unit arrival.
Plans now carry a proper split-and-recombine sequence; from
`plan_feasible_small_s03.out`:

```
compiled_uncouple_front → move_bside_empty_su → compiled_start_request
  → move_bside_occupied_su → compiled_couple_back
  → complete_request_composition
```

All 39 feasible instances contain coupled arrivals or are trivially single-unit,
and 38 of them now solve, so this barrier is gone.

## The converter blocks the whole pipeline

**No plan JSON was written for any of the 47 runs.** All 38 solved runs fail in
`convert_to_tors.py`, which now rejects 8 distinct action types rather than the
single `compiled_adopt_composition` of the previous image:

| unhandled action | occurrences |
|---|---|
| `enter_yard_su` | 188 |
| `compiled_advance_request_N` | 113 |
| `compiled_adopt_composition` | 55 |
| `complete_request_composition` | 36 |
| `compiled_start_request` | 36 |
| `compiled_couple_back` | 36 |
| `compiled_uncouple_front` | 20 |
| `compiled_uncouple_back` | 16 |

The domain rework introduced a new action vocabulary and the converter was not
extended to match. On the planner axis this run is a large win; end to end the
pipeline still emits zero plans.

## What `PLAN IS VALID` does and does not establish

`PLAN IS VALID` comes from the planner image's own `=== VALIDATING PLAN ===`
step, which checks the plan against the same PDDL domain that was just
rewritten. It shows ENHSP's search is consistent with its model. It is **not**
the TORS evaluator and does not show the plan is executable in TORS.

Keep the strength of evidence straight: the `feasible` label on these fixtures
comes from the solver and the evaluator agreeing (see `scenario-feasibility.md`),
which is a much stronger check than a model validating its own output. The
supportable claim from this run is that the model now agrees with ground truth
on **solvability** — not that the plans are correct. Confirming that needs the
evaluator, which needs plan JSON, which needs the converter.

## The one failure: out of memory

`marginal_congestion_s12`, the largest instance at 23 units:

```
java.lang.OutOfMemoryError: Java heap space
  at ...heuristics.advanced.H1.<init>(H1.java:186)
```

This fails while building the `hadd` heuristic, *after* grounding succeeded
(16.5 s, `|F|`=11808). The java invocation in the image carries no `-Xmx`, so it
runs on the JVM default heap. Worth setting an explicit heap size before
concluding the largest instances are out of reach — the other six
`marginal_congestion` instances now solve, where previously all seven were
declared unsolvable, so s12 is at the edge rather than beyond it.

## What to fix next

1. Extend the converter to the new action vocabulary. It is now the only thing
   between the planner and an end-to-end result, and it gates the evaluator
   check that would confirm the plans are actually valid.
2. Set an explicit JVM heap size and re-run `marginal_congestion_s12`.
3. Once plans are being written, run them through the evaluator and compare
   against the fixture plans, to upgrade the claim from "solvable" to "valid".

The earlier advice not to fix the converter first no longer applies: it was
written when infeasible scenarios were being planned anyway, so a converter fix
would have produced TORS plans for impossible scenarios. That risk is gone now
that all 8 infeasible fixtures are correctly rejected.

## Superseded findings

These held against the previous image (runs of 2026-08-12) and are recorded so
they are not re-derived or applied to the current one.

| finding | status |
|---|---|
| 22 of 39 feasible instances wrongly declared unsolvable | fixed |
| Infeasible scenarios planned anyway; no arrival-length constraint | fixed |
| Any coupled arrival causes failure (31 of 31) | fixed |
| `\|X\| = 4 + 2 × (coupled arrivals)` predicts solvability | **retired — do not apply** |
| `marginal_length_s05` vs `s11` as a grounding-bug reproducer | obsolete; both now behave correctly |
| Converter gap limited to `compiled_adopt_composition` | superseded; 8 action types now |

The `|X|` rule is retired rather than fixed: `|X|` rose across the board in the
new image (`feasible_small_s03` 21→26, `marginal_congestion_s12` 48→68) while
`|F|` fell (525→445, 13442→11808), consistent with length and capacity moving
into numeric fluents. The old arithmetic no longer describes anything.

For the record, the previous image's end-to-end results were: 39 feasible runs
producing 8 plans, 22 unsolvable verdicts and 9 converter rejections; 8
infeasible runs producing 7 solved-then-rejected and 1 unsolvable.
