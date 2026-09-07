```markdown
## Repository branch awareness

Five repos make up the pipeline. Run `git branch --show-current` in each
before investigating code or assessing change impact — `main` means
different things depending on the repo, and three of the five also run an
`edge` channel with a different meaning per repo.

| Repo | Branches that matter | Model |
|---|---|---|
| `robust-rail-generator` | `main` | reviewed-only; no `edge` channel |
| `robust-rail-solver` | `main`, `edge` | `edge` is a floating `hip:edge` **image** channel (`stable`/`edge` docker tags) for running an unreviewed fix ahead of review; see its own `CONTRIBUTING.md` |
| `robust-rail-evaluator` | `main`, `edge` | same model as the solver, `tors:edge` image |
| `robust-rail-general` (this repo) | `main`, `edge` | `edge` is a **branch** channel, not an image one — this repo publishes no artifact of its own; see [CONTRIBUTING.md](CONTRIBUTING.md) |
| `robust-rail-planner` | `main` | reviewed-only; no `edge` channel |

The three `edge`s share a name and a branch-flow convention (feature branch →
PR into `main`, optionally merged early into `edge` too via `git merge
--no-ff`), but they are independent of each other — nothing links solver's
`edge` to evaluator's or to this repo's, and there is no single shared
integration branch across repos anymore.

The interchange models (`Location`, `Scenario`, `Plan`, `ScenarioConfig`) live
in this repo as `robust_rail_models` (moved out of the generator, PRs #9/#17,
2026-09-02) — `robust-rail-generator` consumes them rather than owning them,
and the schema this repo's fixtures validate against is this package's own
build output, not a clone of another repo's branch.

## robust-rail-general branch policy

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full `main`/`edge` model.
`main` stays reviewed-only — kept stable so the separate planner team can
coordinate against it — and every change still goes through its own feature
branch and PR into `main`. `edge` is for getting a not-yet-reviewed fix (a
`run_planner.py` change, a new fixture, a docs update) running early, by also
merging its feature branch into `edge` (`git merge --no-ff`) alongside the
normal PR.

## Pipeline integration testing

See [docs/pipeline-integration-testing.md](docs/pipeline-integration-testing.md)
for how to run and compare `stable`/`edge`/`local` pipeline outputs against
each other (including the ad hoc `local-edge` branch convention for checking
several unreviewed PRs together), and
[docs/scenario-feasibility.md](docs/scenario-feasibility.md) /
[docs/roadmap-2.0.0.md](docs/roadmap-2.0.0.md) for the expected outcome of
each fixture scenario and known solver/evaluator defects to check results
against.
```
