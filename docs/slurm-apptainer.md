# Running the pipeline on SLURM via apptainer

`run_generator.py` / `run_solver.py` / `run_planner.py` / `run_evaluator.py`
(and `run_experiment.py`, which drives them) support a second container
engine, apptainer, for running the same pipeline on a SLURM cluster with no
docker daemon on its compute nodes — DelftBlue, specifically. Docker stays
the default; nothing changes for a normal local run.

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
- Pulling is stateful and file-based under apptainer (`apptainer pull`
  produces a real `.sif` you have to name and cache yourself), unlike
  docker's invisible daemon-managed pull cache. See "Staging" below.
- Timeout handling (`docker_utils.run_container`) kills a docker container by
  name (it lives under `dockerd`, a separate process tree an ordinary kill
  can't reach), but for apptainer the invoked process *is* the container, so
  killing its whole process group is enough on its own.
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

SLURM compute nodes have no internet access, so every image a run needs has
to already be sitting in the `.sif` cache before any job is submitted.
`scripts/stage_apptainer_images.py` does this: run it once, by hand, on a
host that does have internet — a DelftBlue login node, confirmed 2026-09-22
to run apptainer directly with no `module load` needed.

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
- Nothing here has yet run against a real DelftBlue login or compute node
  end to end, or through a real `apptainer pull`/`apptainer run` in this
  code path — only unit- and mock-level testing so far. Recommended order
  for a first real trial: stage images for real, run `run_generator.py
  --engine apptainer` by hand on the login node, then a small manually
  submitted array (one or two instances) once the partition/walltime/mem/cpu
  values are known, before trusting it with a full sweep.
