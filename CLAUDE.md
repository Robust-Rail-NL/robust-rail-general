```markdown
## Repository branch awareness

All three repos involved in the 2.0.0 migration have both a legacy branch and an
in-migration branch. Always check which branch is currently checked out before
reading code or drawing conclusions — the branch you're on determines whether you
see protobuf-based code or the new Pydantic/JSON schema code.

| Repo | Legacy / stable branch | Migration branch |
|---|---|---|
| `robust-rail-generator` | `main` | `pydantic` |
| `robust-rail-solver` | `dev` | `noproto` |
| `robust-rail-evaluator` | `main` | `noproto` |
| `scenario-planning-inputs` (this repo) | `main` | `pydantic` |

Run `git branch --show-current` in each repo before investigating code or assessing
change impact. Investigations on the wrong branch will produce incorrect conclusions
about what work is already done and what the real change surface is.

## scenario-planning-inputs branch policy

`main` is kept stable for coordination with the separate planner team. It contains
only design decisions (docs, config fixes) that do not break the existing pipeline.

`pydantic` is where all Phase 1 implementation work lives:
- `location_unified.json` renamed to `location.json`
- `run_solver.py` reads `scenario_*.json` (unified) instead of `scenario_solver_*.json`
- `run_planner.py` reads `location.json` instead of `location_solver.json`
- Future: integration test results once solver and evaluator are updated

All Phase 1 and later work in this repo goes on the `pydantic` branch.
```
