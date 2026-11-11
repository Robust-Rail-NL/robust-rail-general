"""Tests for run_visualizer.py: layout name derivation and plan lookup."""

from pathlib import Path

from run_visualizer import find_plans, layout_name


def test_layout_name_snake_cases_location_dir():
    assert layout_name(Path("Location_KleineBinckhorst")) == "kleine_binckhorst"
    assert layout_name(Path("Location_SimpleService")) == "simple_service"


def test_find_plans_only_plan_jsons(tmp_path):
    plans = tmp_path / "Location_X" / "plans"
    plans.mkdir(parents=True)
    for name in ("plan_a.json", "plan_a.html", "plan_a.out", "other.json"):
        (plans / name).touch()
    assert find_plans([tmp_path / "Location_X"]) == [plans / "plan_a.json"]
