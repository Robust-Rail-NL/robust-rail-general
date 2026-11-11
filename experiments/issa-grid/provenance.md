# Provenance of the Issa grid results

Written 2026-11-08, after the first pass and the extension had finished. Every run of `results/issa_grid.csv` used one build per tool (the `build` column).

## What ran

| Component | Build string (first line of the tool's output) | Full commit | Image digest (DAIC `.sif.digest`) |
|---|---|---|---|
| solver (HIP), image `ghcr.io/robust-rail-nl/hip:edge` | `HIP 2.2.0-edge+20261106.965fd71` | `965fd7192a7e35bfede7635ae6ede1ce84460e7b` (robust-rail-solver, branch `edge`, a "Merge branch 'main' into edge" that includes PR #79, the fix for #75) | `sha256:166c67bf3c37a5cfd078fab66872062369a7ed37ea8468b15b856fcace863bd2` |
| planner, image `ghcr.io/robust-rail-nl/planner:edge` | `robust-rail-planner 0.5.0-edge+20261106.2f2f34b` | `2f2f34b0157a4846762ced82fc925b5218b3fb0f` (robust-rail-planner, branch `edge`, includes PR #60 timing/stats lines and #59) | `sha256:129bbf432bb37812733262827775dc1009d9c209b308604754b150ac806c8125` |
| generator, image `ghcr.io/robust-rail-nl/generator:latest` | v2.5.0 | `a3271fd0df499353d3234371e5444031b578366f` (tag `v2.5.0`) | `sha256:61b62221ee3ea872658e38189bdfab307b703f1d97010082ab32fca80a6c23e9`; the Apptainer image id of the generation (`sif:45113344:1794038133976907888`) is in every `scenario_<instance>.generator.json` (`generator_image_id`) |
| evaluator (TORS), image `ghcr.io/robust-rail-nl/tors:edge` | `TORS 2.3.0-edge+20261103.50bc79e` (first line of `local_search/eval.out`) | not recorded | `sha256:bb0dd3d40b3de14d3726242d6f8eac768717f50bb3293ead9ad73b723ef90727` |
| experiment tooling | robust-rail-general `main` at `8fea78e55a867c515bd6bf4966622e459987bd45` plus branch `daic-port` (tip `430ddf0`, before it was rebased onto `main`; the rebased branch has the same changes) merged locally on DAIC | | |

## Released versions

The runs used edge images, which print `-edge+<date>.<commit>` in their version line. The three tools were released afterwards from `main`, and each release tag differs from the commit that was run only in the version and release-notes files (checked 2026-11-11 with `git diff --stat <run commit> <tag>`). The results can therefore be attributed to these releases:

| Tool | Release | Tag commit | Run commit | Files changed between them |
|---|---|---|---|---|
| solver (HIP) | v2.3.0 | `75997d7` | `965fd71` | `RELEASE_NOTES.md`, `ServiceSiteScheduling/HIP.csproj` |
| planner | v0.6.0 | `5969d1b` | `2f2f34b` | `RELEASE_NOTES.md`, `VERSION` |
| evaluator (TORS) | v2.4.0 | `55a112a` | `50bc79e` | `CMakeLists.txt`, `RELEASE_NOTES.md` |

The generator was already released (v2.5.0). The `build` column of the CSV keeps the edge strings that were actually run. A rerun with the released images has not been done.

## Runs behind the CSVs

The digests are those of the staged images (`.sif.digest` files, staged 2026-11-07 for the generator, solver and planner, 2026-11-04 for TORS) and were not restaged during the runs. The generator and its scenarios are shared by both passes.

`results/first_grid.csv` (first pass) and the first part of `results/issa_grid.csv`: SLURM array ids on DAIC (task index = row of `tasks.tsv`, largest scenarios first): servicing off, 1 to 6 trains: 110812 (solver), 110813 (enhsp), 110814 (symbolic-rail); servicing on, 2 to 6 trains: 110986, 110987, 110988; servicing off, 7 to 10 trains: 112992, 112993, 112994; servicing on, 7 to 10 trains: 113037, 113038, 113039. The first servicing-on submission (110818 to 110820) was cancelled by the scheduler because its generate job exited 1 (1 train with servicing cannot be generated). Their accounting is in `results/sacct_first_grid.txt`.

The extension (instances 5 to 14, trains 3 to 8, enhsp at 3 and 4 trains only, 420 tasks per variant, output directories `issa_grid_ext_off` and `issa_grid_ext_on`), submitted 2026-11-08 with `PRUNE_MANIFEST=1`: servicing off 120634 (solver), 120635 (enhsp), 120636 (symbolic-rail); servicing on 120639, 120640, 120641. Accounting in `results/sacct_extension.txt`. Other array ids of the same directories in `grid_jobs.txt` with id 0 are dry runs.

`results/issa_grid.csv` joins both passes: 1740 rows, of which 45 are `no_scenario` (1 train, servicing on).

## Experiment definitions

`issa_grid_servicing_{off,on}.json` (seed 700, trains 1 to 10, 3 matchings, 5 instances, `max_duration` 1800, `reject_infeasible` true) and, for the extension, `issa_grid_ext_servicing_{off,on}.json` (`number_of_instances` 15, instances 5 to 14 run, trains 3 to 8, enhsp trains 3 and 4 only). The scenarios of instances 0 to 4 are identical in both because the generator seeds an instance as `seed*(j+i+1)`.

Hardware: DAIC partition `daic-eemcs-st`, every node an Intel Xeon 6724P (32 CPUs, 4.3 GHz max, about 512 GB; `lscpu` output of jobs 123823 to 123827), nodes `gpu47`, `gpu48`, `gpu49`, `gpu51`, `gpu52` (per-run node in the CSV column `node`), 1 CPU per task, memory per task 4G (solver), 32G (enhsp), 12G (symbolic-rail), 45 min limit, 1800 s tool budget.

Servicing on has no 1-train cell: the generator refuses it (time window 1440, servicing time 300, `min_gap_on_gateway` 480).
