# Contributing

## Branch channels: `main` and `edge`

This repo holds orchestration scripts (`run_*.py`), the fixture corpus, and
schema/docs shared across the 2.0.0-era repos. It publishes no artifact of
its own, so unlike [`robust-rail-solver`](https://github.com/Robust-Rail-NL/robust-rail-solver)'s
`stable`/`edge` **image** channels, the channel here is a **branch** —
there's nothing to build or push, only somewhere to land work before it's
reviewed.

- **`main`** — the reviewed path. Kept stable on purpose: the planner team
  coordinates against it, so a change lands here only via its own PR.
- **`edge`** — a fast, lower-ceremony branch for running a not-yet-reviewed
  fix (a `run_planner.py` change, a new fixture, a docs update) without
  waiting for its PR into `main`. There's no image to publish, so getting
  something onto `edge` *is* the whole act — anyone who wants it early just
  checks it out.

### Branch flow

Mirrors the convention `robust-rail-solver` established for its own `edge`:

- **Every change still goes through its own feature branch and PR into
  `main`.** `edge` does not replace that — it runs alongside it. Never
  commit directly to `edge`.
- **To get a fix onto `edge` early**, merge its feature branch into `edge`
  (`git merge --no-ff <branch>`) in addition to opening the normal PR into
  `main`. Once that PR is reviewed and merged, `edge` already has the
  content — nothing needs to be cherry-picked or re-applied.
- **`edge` only ever advances via merge commits** (`git merge --no-ff`),
  whether merging in a feature branch or catching up with `main`. Never
  rebase `edge`, and never fast-forward it — the point is for its history to
  show what was merged in and when, as a readable sequence of merge commits,
  not a flattened line that hides which branch each change came from.
- **Flow between `edge` and `main` is one-directional**: `main → edge`
  only, via periodic `git merge --no-ff main`. Nothing flows from `edge`
  back into `main` directly, since nothing should ever exist on `edge` that
  doesn't also exist on some reviewed feature branch (see above).
- One accepted gap: if `edge` is ever force-pushed or rebased despite the
  above, a dropped commit won't show up in `git log` — only `git reflog`
  would have it. Treated as a reasonable tradeoff for a fast-moving branch;
  revisit only if that actually causes a real problem.

### CI

Both `.github/workflows/validate-fixtures.yml` and `pipeline-smoke.yml`
trigger on `main` and `edge`. A push to `edge` runs the same checks a PR
into `main` would, so a fix picked up early is at least validated early too
— it just hasn't been reviewed yet.

## Retired: the `dev` branch

`dev` predated the 2.0.0 schema unification and tracked the old
protobuf-based pipeline. It was fully merged into `main` before the 2.0.0
release and has carried no unique history since, so it's been deleted
outright rather than folded into `edge` — there was nothing on it that
`main` didn't already have.
