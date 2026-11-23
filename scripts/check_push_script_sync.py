#!/usr/bin/env python3
"""Check that the shared blocks in the sibling repos' docker-push*.sh, bump-version.sh and edge-commit hook scripts have not drifted apart.

The push scripts (docker-push.sh, docker-push-edge.sh) in robust-rail-evaluator, -planner, -solver and
-generator share some logic: the -f flag, the release / edge safety guards, the ghcr.io login and the
buildx builder setup. The bump-version.sh scripts (those four plus this repo) share the clean-tree check,
usage, the existing-tag guard, semver arithmetic and the commit/tag step. The edge-commit guard (refuse a direct commit to edge, allow a `git merge --no-ff`
to finish) is shared by the git hooks of all five repos. Each repo has to stay publishable from a standalone clone, and a release script
must run exactly as committed at its tag, so the logic is copied into each script rather than sourced
from here. Copies drift, so each copy is wrapped in marker lines:

    # BEGIN SHARED BLOCK: <name> ...
    ...
    # END SHARED BLOCK: <name>

and this script compares the text between the markers across every script that has the block. It also
fails if a script lacks a block it should have, or has one more than once, or one without an end marker.
Only the text between the markers is compared; the marker lines themselves may differ.

It checks the working copies of the sibling repos, i.e. whatever branch each has checked out.

To change shared logic: edit the block in all copies, then run this script.

Usage:
    ./check_push_script_sync.py [--root DIR]    # DIR holds the robust-rail-* checkouts; default: parent of this repo
"""

import argparse
import difflib
import sys
from pathlib import Path

BEGIN = "# BEGIN SHARED BLOCK: "
END = "# END SHARED BLOCK: "

RELEASE_BLOCKS = ("release-flags", "release-guards", "ghcr-login", "buildx-builder")
EDGE_BLOCKS = ("edge-guards", "ghcr-login", "buildx-builder")
EDGE_COMMIT_BLOCKS = ("edge-commit-guard",)
BUMP_BLOCKS = ("bump-clean-tree", "bump-usage", "bump-tag-exists", "bump-commit-tag")
# The evaluator keeps its release and prerelease suffix in two separate CMake variables, so its bump-version.sh
# has its own arithmetic; the other four derive both from a single version string.
BUMP_SEMVER_BLOCKS = (*BUMP_BLOCKS, "bump-semver")

# This repo is checked at its own location (the checkout containing this script), whatever the directory is called.
SELF_REPO = "robust-rail-general"
SELF_ROOT = Path(__file__).resolve().parents[1]

# (path relative to --root, blocks that script must contain)
SCRIPTS = [
    ("robust-rail-evaluator/docker-push.sh", RELEASE_BLOCKS),
    ("robust-rail-planner/docker-push.sh", RELEASE_BLOCKS),
    ("robust-rail-solver/ServiceSiteScheduling/docker-push.sh", RELEASE_BLOCKS),
    ("robust-rail-generator/docker-push.sh", RELEASE_BLOCKS),
    ("robust-rail-evaluator/docker-push-edge.sh", EDGE_BLOCKS),
    ("robust-rail-planner/docker-push-edge.sh", EDGE_BLOCKS),
    ("robust-rail-solver/ServiceSiteScheduling/docker-push-edge.sh", EDGE_BLOCKS),
    ("robust-rail-generator/docker-push-edge.sh", EDGE_BLOCKS),
    ("robust-rail-evaluator/bump-version.sh", BUMP_BLOCKS),
    ("robust-rail-planner/bump-version.sh", BUMP_SEMVER_BLOCKS),
    ("robust-rail-solver/ServiceSiteScheduling/bump-version.sh", BUMP_SEMVER_BLOCKS),
    ("robust-rail-generator/bump-version.sh", BUMP_SEMVER_BLOCKS),
    (f"{SELF_REPO}/bump-version.sh", BUMP_SEMVER_BLOCKS),
    # The guard that refuses a direct commit to edge but lets a `git merge --no-ff` finish. The generator's is
    # a script run by its pre-commit config; the others are the pre-commit hook itself.
    ("robust-rail-evaluator/.githooks/pre-commit", EDGE_COMMIT_BLOCKS),
    ("robust-rail-planner/.githooks/pre-commit", EDGE_COMMIT_BLOCKS),
    ("robust-rail-solver/.githooks/pre-commit", EDGE_COMMIT_BLOCKS),
    ("robust-rail-generator/.githooks/edge-commit-guard.sh", EDGE_COMMIT_BLOCKS),
    (f"{SELF_REPO}/.githooks/pre-commit", EDGE_COMMIT_BLOCKS),
]


def extract_blocks(text: str, label: str, problems: list[str]) -> dict[str, list[str]]:
    """Return {block name: lines between its markers}; append a message to `problems` for malformed blocks."""
    blocks: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        if line.startswith(BEGIN):
            name = line[len(BEGIN) :].split()[0]
            if current is not None:
                problems.append(f"{label}: block '{name}' begins inside block '{current}'")
            if name in blocks:
                problems.append(f"{label}: block '{name}' appears more than once")
            current = name
            blocks[name] = []
        elif line.startswith(END):
            name = line[len(END) :].split()[0]
            if current != name:
                problems.append(f"{label}: END marker for '{name}' does not match open block '{current}'")
            current = None
        elif current is not None:
            blocks[current].append(line)
    if current is not None:
        problems.append(f"{label}: block '{current}' has no END marker")
    return blocks


def check(root: Path, scripts=SCRIPTS, self_root: Path = SELF_ROOT) -> list[str]:
    """Return a list of problems; empty means every shared block is present and identical."""
    problems: list[str] = []
    copies: dict[str, list[tuple[str, list[str]]]] = {}  # block name -> [(script, lines)]
    for rel, expected in scripts:
        repo, _, inside = rel.partition("/")
        path = self_root / inside if repo == SELF_REPO else root / rel
        if not path.is_file():
            problems.append(f"{rel}: not found under {root}")
            continue
        blocks = extract_blocks(path.read_text(), rel, problems)
        for name in expected:
            if name not in blocks:
                problems.append(f"{rel}: missing shared block '{name}'")
        for name, lines in blocks.items():
            copies.setdefault(name, []).append((rel, lines))
    for name, found in copies.items():
        ref_rel, ref_lines = found[0]
        for rel, lines in found[1:]:
            if lines != ref_lines:
                diff = "\n".join(difflib.unified_diff(ref_lines, lines, ref_rel, rel, lineterm="", n=1))
                problems.append(f"shared block '{name}' differs between {ref_rel} and {rel}:\n{diff}")
    return problems


def main() -> int:
    default_root = Path(__file__).resolve().parents[2]
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--root", type=Path, default=default_root, help=f"directory holding the sibling repos (default: {default_root})"
    )
    args = ap.parse_args()
    problems = check(args.root)
    for p in problems:
        print(p, file=sys.stderr)
    if problems:
        print(f"\n{len(problems)} problem(s): the shared script blocks are out of sync.", file=sys.stderr)
        return 1
    print(f"OK: shared blocks identical across {len(SCRIPTS)} scripts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
