# Running the pipeline on SLURM via apptainer

`run_generator.py` / `run_solver.py` / `run_planner.py` / `run_evaluator.py`
(and `run_experiment.py`, which drives them) support a second container
engine, apptainer, for running the same pipeline on a SLURM cluster with no
docker daemon on its compute nodes — DelftBlue, specifically. Docker stays
the default; nothing changes for a normal local run.

## Prerequisites on DelftBlue

`pyproject.toml` requires Python `>=3.12`; DelftBlue's default `python3`
(3.9.25 as of 2026-09-24) doesn't meet it, and every `run_*.py`/`docker_utils.py`
import fails immediately with a `TypeError` on an `X | None` type hint,
pointing at whatever line happens to define one first -- not an error about
Python versions at all, easy to mistake for a real bug. A new-enough Python
is available, but hidden behind a hierarchical Lmod module (found via
`module spider python`, the same way apptainer's own `module spider`
discovery works, if it's ever needed):
```bash
module load 2026 cpu
module load python/3.13.12
```
apptainer itself needed no `module load` (confirmed 2026-09-22, directly on
`PATH`) -- only Python did.

## The engine abstraction

Every script takes `--engine {docker,apptainer}` (default `docker`) and
`--sif-cache-dir DIR` (default `~/apptainer-images`,
`docker_utils.DEFAULT_SIF_CACHE_DIR`), added by `docker_utils.add_engine_args`.
Container invocations go through `docker_utils.build_run_cmd(engine, image,
mounts, args, ...)` instead of each script building a `docker run ...` argv
by hand, so the two engines' differences live in one place:

- No daemon under apptainer — `ensure_runtime_ready("apptainer")` just checks
  the binary is on `PATH`; there's nothing like `docker info` to reach.
- No `--user uid:gid` under apptainer — it already runs as the invoking user.
- `--mount type=bind,source=A,target=B` (docker) becomes `--bind A:B`
  (apptainer).
- `docker run <image> <args>` (docker) becomes `apptainer run <sif> <args>`
  (apptainer) — **not** `apptainer exec`. Every image here has a Docker
  `ENTRYPOINT`, and each script's `args` (`--config ...`, `--mode ...`, etc.)
  are meant as arguments *to* it, exactly like `docker run`'s own contract.
  `apptainer run` invokes the `.sif`'s converted-from-`ENTRYPOINT` runscript
  with `args` appended; `apptainer exec` ignores the entrypoint and tries to
  execute `args[0]` itself as a command, which a `--flag` never is. For a
  bare sanity check of a staged image (no args, entrypoint's own default
  behaviour), `apptainer run <sif>` is also the right command — it needs no
  in-container executable path, unlike `exec`.
- Docker starts a container in the image's own Dockerfile `WORKDIR`;
  apptainer does not — it mirrors the *host's* current working directory
  inside the container instead. Every one of these images' `ENTRYPOINT`s is
  a path relative to its `WORKDIR` (generator's `python src/main.py`,
  solver's `dotnet ServiceSiteScheduling.dll`, evaluator's `build/TORS`), so
  without correcting this, the entrypoint fails looking for that relative
  path under wherever apptainer happened to be invoked from, not the image's
  own directory. Each `run_*.py` defines its own `CONTAINER_WORKDIR`
  constant (`/app` for generator/solver/planner, `/workspace` for the
  evaluator — its Dockerfile differs) and passes it as `build_run_cmd`'s
  `workdir` argument, which becomes apptainer's `--pwd`; docker ignores it,
  since it never needed the correction. Caught 2026-09-24 running a bare
  `apptainer run <sif>` sanity check by hand on DelftBlue.
- A `.sif`'s squashfs is read-only by default; docker gives every container
  its own writable layer automatically, with no volumes needed. The solver
  in particular always writes debug snapshots to a hardcoded, non-
  configurable `./tmp_plans/` internally (HIP's `Program.cs`/
  `TabuSearch.cs`), which fails outright ("Read-only file system") without
  correcting for this — also caught 2026-09-24, running the bare `hip-
  stable.sif` sanity check. Fixed with `apptainer run --writable-tmpfs`,
  unconditionally for every apptainer invocation (not just the solver's):
  an ephemeral in-memory overlay across the whole container filesystem,
  equivalent to docker's free writable layer. Any of these images could
  plausibly have similar internal scratch-write behaviour that hasn't been
  audited for, hence unconditional rather than solver-only.
- Pulling is stateful and file-based under apptainer (`apptainer pull`
  produces a real `.sif` you have to name and cache yourself), unlike
  docker's invisible daemon-managed pull cache. See "Staging" below.
- Timeout handling (`docker_utils.run_container`) kills a docker container by
  name (it lives under `dockerd`, a separate process tree an ordinary kill
  can't reach), but for apptainer the invoked process *is* the container, so
  killing its whole process group is enough on its own. That relies on
  `_run_once` launching it with `start_new_session=True` (its own session,
  detached from the terminal) so the process-group kill has something clean
  to target -- side effect: if you run something under `--engine apptainer`
  interactively on a login node, Ctrl-Z/Ctrl-C only reaches the outer
  `python3 run_*.py` driver, never the `apptainer run ...` process (and
  whatever it launches, e.g. ENHSP's `java`) it started, since that's no
  longer in the terminal's own foreground process group. It'll keep running,
  invisible, until it finishes or is found and killed directly:
  ```bash
  ps -ef | grep -E 'apptainer|java' | grep -v grep
  ps -o pgid= -p <pid>      # get its process group id
  kill -9 -- -<pgid>        # kill the whole group, not just one pid
  ```
  Doesn't affect the real SLURM path: `scancel`/a walltime kill goes through
  SLURM's own cgroup-based job containment, which reaches every process in a
  job step regardless of our own process-group structure. This only bites
  interactive, manual testing on a login node -- exactly what you'd be doing
  to sanity-check before handing this off. Found 2026-09-24 running a
  planner sanity check by hand on DelftBlue.
- The macOS Docker-Desktop bind-mount-race workaround in `docker_utils.py` is
  docker-only and inert under apptainer.

There is no apptainer equivalent of docker's `--version local` (a bare,
locally-built tag like `hip:latest` with no registry to pull from) — nothing
to stage, nothing to resolve a `.sif` from. `run_experiment.py` checks for
this up front under `--engine apptainer` and fails with a clear message
naming the offending `--*-version` flag (e.g. its own `--planner-version`
default, `local`) rather than letting it surface four subprocess calls deep
as an opaque "not staged" error.

## Staging images

Every image a run needs is staged into a `.sif` cache before any job is
submitted, via `scripts/stage_apptainer_images.py` run once by hand on the
login node (confirmed 2026-09-22 to run apptainer directly with no `module
load` needed).

This was originally written assuming SLURM compute nodes have no internet
access at all -- **not confirmed**: an interactive `srun` session on
`compute-p1` (2026-09-25) reached both `ghcr.io` and a general internet
host (`curl -sI` to each succeeded), contradicting that assumption, at
least for that partition. Whether this holds cluster-wide (or was
`compute-p1`-specific) wasn't checked further, and DelftBlue has no
documented network-isolation policy for compute nodes the way it has a
`/scratch` storage one (see "Storage" below) -- worth confirming with
DelftBlue's own docs/support before relying on either way. Staging upfront
stays the right call regardless of the answer: avoiding a few hundred
array tasks each hitting the registry independently (redundant round-trips
for an image that cannot change mid-run, registry flakiness able to abort
an unrelated task, the same reasoning `run_experiment.py`'s own
`_pull_once` already uses for docker) is worth doing whether or not it's
also a hard requirement.

It resolves `--<tool>-version` (comma-separated) through each `run_*.py`'s
own `DOCKER_IMAGE_VERSIONS`, de-duplicates by resolved image before pulling
(several version names can share one image — e.g. the generator's
`stable`/`stable-assert`/`edge` all do), and pulls each distinct one into
`--cache-dir` as `<sanitized-image-ref>.sif`
(`docker_utils.sif_filename`/`sif_path`). Defaults to the set a normal sweep
needs: generator/solver/planner `stable`, evaluator `stable` *and*
`stable-assert` (a full solver-vs-planner comparison needs both eventually,
just never in the same `run_evaluator.py` invocation). `--edge` adds each
tool's edge channel; `--force` re-pulls.

Measured 2026-09-22 on DelftBlue: that default 5-image set is 607MiB total —
about 2% of `/home`'s 30GiB quota, lighter than expected even with the
planner's Julia runtime included.

Separately, `apptainer pull` also populates apptainer's own layer/download
cache at `~/.apptainer` (1.3GiB after staging the default set on
2026-09-24) — distinct from the `.sif` cache above, and not read at all by
`apptainer run`/`exec` against an already-built `.sif`; it only speeds up a
*future* re-stage. Safe to reclaim any time with `apptainer cache clean`
(everything in it is already baked into the staged `.sif` files), and worth
redirecting to `/scratch` for future staging runs rather than letting it
compete with `/home`'s quota:
```bash
export APPTAINER_CACHEDIR=/scratch/$USER/.apptainer-cache
```
Deliberately not something `stage_apptainer_images.py` sets itself — a
`/scratch/<username>/...` path is personal and DelftBlue-specific, not
something a shared, checked-in script should assume (same reasoning as the
`ghcr.io` credential helper being personal dotfiles rather than repo code).

## Storage: `.sif` cache on `/home`, `--output-dir` on `/scratch`

DelftBlue quotas (2026-09-22): `/home` 30GiB, `/scratch` 5TiB. `/scratch` has
no confirmed purge policy yet, but the login banner states one is coming
("The usage of /scratch still needs to be reduced. Measures are coming to
(en)force the removal of inactive data from /scratch.") — not active, but a
clear signal, and a completed, untouched experiment output directory is
exactly "inactive data."

So: the `.sif` cache lives on `/home` (small — 607MiB for the default set —
and fixed-size regardless of sweep size; a queued job array can't afford to
have it swept mid-run). A sweep's `--output-dir` lives on `/scratch` during
the run (it grows with instances × tools × seeds, and 5TiB gives real
headroom `/home` doesn't). The aggregation step (below) copies results back
to `/home` before a run counts as done — nothing on `/scratch` is the final
resting place for anything from a run, whether or not purging has actually
started.

## Running a sweep as a SLURM job array

1. **Stage images** (once, or whenever `DOCKER_IMAGE_VERSIONS` changes):
   `python3 scripts/stage_apptainer_images.py`.
2. **Generate scenarios**, directly on the login node:
   `python3 run_generator.py --location <NAME> --engine apptainer`.
3. **Build the manifest**: `python3 scripts/slurm_manifest.py --location
   <NAME> --tools solver,planner [--num-seeds N] --output-dir <SCRATCH_DIR>`.
   Enumerates the sweep's (instance, tool[, seed]) work units — reusing
   `run_experiment.py`'s own instance resolution and mirroring
   `_run_instance`'s per-tool/per-seed loop exactly, so an array-job sweep
   and a local `--jobs N` sweep of the same flags produce identical layouts
   (`<output-dir>/<instance>/local_search[/seed<i>]/`,
   `<output-dir>/<instance>/planning/`). Writes `tasks.tsv` and prints the
   `sbatch` command to run next.
4. **Submit the array job**: the printed
   `sbatch --array=0-N scripts/slurm/run_experiment_array.sbatch <manifest>
   <location> <output-dir>` command. Each task runs
   `scripts/slurm_run_task.py`, which reads its row (by `--index`, defaulting
   to `$SLURM_ARRAY_TASK_ID`) and calls `run_experiment.py`'s own
   `_run_and_record` directly — the same solver/planner-then-evaluator
   sequence a local run uses, not a reimplementation of it.

   `scripts/slurm_run_task.py` itself — the exact code each array task
   runs — was confirmed working end to end on a real DelftBlue compute node
   (`compute-p1`, interactive `srun`, 2026-09-25): `python3
   scripts/slurm_run_task.py --index 0 --manifest <tasks.tsv> --location
   <NAME> --output-dir <dir>` produced a plan (solver) and scored it
   (evaluator), both exiting cleanly. What's still untried is `sbatch
   --array` itself doing the scheduling/indexing — see "Known gaps".
5. **Submit the aggregation job**, depending on the array job:
   `sbatch --dependency=afterok:<array_job_id> scripts/slurm/aggregate.sbatch
   <output-dir> <home-dest>`. Runs `report_results.py` +
   `coverage_analysis.py` over `--output-dir`, then `rsync`s the whole tree
   to `<home-dest>` (see "Storage" above).

## Known gaps

- `scripts/slurm/run_experiment_array.sbatch` and `aggregate.sbatch` have
  placeholder `#SBATCH` values (`--partition`, `--time`, `--cpus-per-task`,
  `--mem`) — `sbatch` will refuse to submit until these are filled in,
  deliberately, rather than running with a guessed number.
  `--account=research-eemcs-st` is filled in.
- Still genuinely untried: an actual `sbatch --array` submission and the
  aggregation job. Blocked on the partition/walltime/mem/cpu placeholders
  above.
- Recommended next step: a small manually submitted array (one or two
  instances) once those values are known.
