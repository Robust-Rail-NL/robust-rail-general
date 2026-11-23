"""Tests for run_visualizer.py: layout name derivation and plan lookup."""

import subprocess
import sys
from pathlib import Path

from run_visualizer import find_plans, layout_name

ROOT = Path(__file__).resolve().parent.parent


def test_layout_name_snake_cases_location_dir():
    assert layout_name(Path("Location_KleineBinckhorst")) == "kleine_binckhorst"
    assert layout_name(Path("Location_SimpleService")) == "simple_service"


def test_find_plans_only_plan_jsons(tmp_path):
    plans = tmp_path / "Location_X" / "plans"
    plans.mkdir(parents=True)
    for name in ("plan_a.json", "plan_a.html", "plan_a.out", "other.json"):
        (plans / name).touch()
    assert find_plans([tmp_path / "Location_X"]) == [plans / "plan_a.json"]


def test_s_is_short_for_single():
    result = subprocess.run(
        [sys.executable, str(ROOT / "run_visualizer.py"), "-s", "no_such_instance_xyz"],
        capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 1
    assert "matched no files" in result.stderr
