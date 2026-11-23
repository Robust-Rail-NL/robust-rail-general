"""The --version names of each run_*.py resolve to the image channels the docs
promise: every tool has an `edge` image of its own, distinct from `stable`."""

from pathlib import Path

import pytest

from scripts.docker_utils import load_image_versions

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("script, image", [
    ("run_generator.py", "ghcr.io/robust-rail-nl/generator:edge"),
    ("run_solver.py", "ghcr.io/robust-rail-nl/hip:edge"),
    ("run_evaluator.py", "ghcr.io/robust-rail-nl/tors:edge"),
    ("run_planner.py", "ghcr.io/robust-rail-nl/planner:edge"),
])
def test_edge_version_resolves_to_the_edge_image(script, image):
    versions = load_image_versions(ROOT / script)
    assert versions["edge"] == image
    assert versions["edge"] != versions["stable"]
