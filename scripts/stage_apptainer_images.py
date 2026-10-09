#!/usr/bin/env python3
"""Stage every apptainer .sif image the pipeline needs into a shared cache.

Run once, by hand, on a host with internet access -- a DelftBlue login node,
confirmed 2026-09-22 to run apptainer directly with no `module load` needed
(see docs/slurm-apptainer.md). SLURM compute nodes have none, so every image
a job array will need has to already be sitting in the cache before any job
is submitted: scripts.docker_utils.ensure_sif_present (what build_run_cmd's
apptainer path calls) never falls back to pulling on its own -- a missing
.sif there is a hard error pointing back at this script, not something a
compute node fixes for itself.

Mirrors run_experiment.py's own _pull_once: images are resolved from each
run_*.py's own DOCKER_IMAGE_VERSIONS (the single source of truth for what a
--version name means) and de-duplicated by image ref before pulling, since
several version names can resolve to the identical image -- e.g. the
generator's stable/stable-assert/edge all do.

No --version local equivalent: decided against one (see docs/
slurm-apptainer.md) since only registry images matter for a cluster run.
--evaluator-version defaults to staging both stable and stable-assert,
not just one: a full solver/planner comparison run needs both eventually,
just never in the same run_evaluator.py invocation (its --version takes one
value at a time). Measured 2026-09-22: generator + hip stable + tors
stable + tors stable-assert + planner stable = 607MiB total, ~2% of the
30GiB --cache-dir default's home quota.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.docker_utils import (  # noqa: E402
    DEFAULT_SIF_CACHE_DIR, apptainer_pull, ensure_runtime_ready, load_image_versions,
)

# script name -> the --version value(s) a normal sweep actually needs staged.
# Order here is only for a stable, readable print order below.
DEFAULT_VERSIONS = {
    "run_generator.py": ["stable"],
    "run_solver.py": ["stable"],
    "run_planner.py": ["stable"],
    "run_evaluator.py": ["stable", "stable-assert"],
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pull every apptainer .sif image the pipeline needs into a shared cache, "
                    "once, from a host with internet access (e.g. a DelftBlue login node)."
    )
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_SIF_CACHE_DIR, metavar="DIR",
                        help=f"Where to write .sif files (default: {DEFAULT_SIF_CACHE_DIR}). Must be "
                             "readable from every compute node a job array will run on -- /home, "
                             "not /scratch, on DelftBlue (see docs/slurm-apptainer.md for why).")
    parser.add_argument("--generator-version", default=",".join(DEFAULT_VERSIONS["run_generator.py"]),
                        metavar="V[,V...]",
                        help="Comma-separated --version value(s) to stage for run_generator.py "
                             f"(default: {','.join(DEFAULT_VERSIONS['run_generator.py'])}).")
    parser.add_argument("--solver-version", default=",".join(DEFAULT_VERSIONS["run_solver.py"]),
                        metavar="V[,V...]",
                        help="Comma-separated --version value(s) to stage for run_solver.py "
                             f"(default: {','.join(DEFAULT_VERSIONS['run_solver.py'])}).")
    parser.add_argument("--planner-version", default=",".join(DEFAULT_VERSIONS["run_planner.py"]),
                        metavar="V[,V...]",
                        help="Comma-separated --version value(s) to stage for run_planner.py "
                             f"(default: {','.join(DEFAULT_VERSIONS['run_planner.py'])}).")
    parser.add_argument("--evaluator-version", default=",".join(DEFAULT_VERSIONS["run_evaluator.py"]),
                        metavar="V[,V...]",
                        help="Comma-separated --version value(s) to stage for run_evaluator.py "
                             f"(default: {','.join(DEFAULT_VERSIONS['run_evaluator.py'])} -- both, "
                             "since a full comparison run needs both eventually).")
    parser.add_argument("--edge", action="store_true",
                        help="Also stage each tool's 'edge' channel alongside the version(s) above.")
    parser.add_argument("--force", action="store_true",
                        help="Re-pull even if a .sif already exists in --cache-dir.")
    args = parser.parse_args()

    ensure_runtime_ready("apptainer")

    versions = {
        "run_generator.py": args.generator_version.split(","),
        "run_solver.py": args.solver_version.split(","),
        "run_planner.py": args.planner_version.split(","),
        "run_evaluator.py": args.evaluator_version.split(","),
    }
    if args.edge:
        for version_list in versions.values():
            version_list.append("edge")

    seen_images: dict[str, str] = {}  # image -> first (script, version) that named it
    for script, version_list in versions.items():
        image_versions = load_image_versions(ROOT / script)
        for version in version_list:
            if version not in image_versions:
                sys.exit(f"ERROR: {script} has no --version {version!r} "
                         f"(choices: {', '.join(image_versions)}).")
            image = image_versions[version]
            if image in seen_images:
                print(f"{script} --version {version} -> {image}  "
                      f"(same image as {seen_images[image]})")
                continue
            seen_images[image] = f"{script} --version {version}"
            print(f"{script} --version {version} -> {image}")
            apptainer_pull(image, args.cache_dir, args.force)

    print(f"\nDone: {len(seen_images)} distinct image(s) staged in {args.cache_dir}.")


if __name__ == "__main__":
    main()
