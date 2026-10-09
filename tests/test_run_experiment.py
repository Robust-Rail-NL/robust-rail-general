"""Tests for run_experiment's self-contained results/<name>/ layout: the sweep
the "scenario_config" section expands to, and the --experiment / --scenario
commands the run_*.py scripts build for it."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

import run_experiment
from scripts import experiment_spec
from scripts.generate_experiment_configs import DEFAULTS, scenario_params, sweep_configs
from scripts.report_results import _scenario_for

ROOT = Path(__file__).resolve().parent.parent
LOCATION = "Location_KleineBinckhorst"


def _spec(**scenario_config) -> dict:
    return {"name": "demo", "location": LOCATION, "scenario_config": scenario_config}


def test_sweep_configs_names_and_seeds():
    params = scenario_params(_spec(number_of_trains=[3, 5], matchings=["FIFO", "LIFO"],
                                   number_of_instances=2, seed=7, time_window_per_train=400))
    configs = sweep_configs(params, LOCATION)

    assert list(configs) == [
        "custom_3_FIFO_0", "custom_3_FIFO_1", "custom_3_LIFO_0", "custom_3_LIFO_1",
        "custom_5_FIFO_0", "custom_5_FIFO_1", "custom_5_LIFO_0", "custom_5_LIFO_1",
    ]
    config = configs["custom_5_LIFO_1"]
    assert config["location"] == "KleineBinckhorst"
    assert config["number_of_trains"] == 5
    assert config["end_time"] == 5 * 400
    assert config["seed"] == 7 * (1 + 1 + 1)  # seed * (j + i + 1)
    assert config["matching"] == 2


def test_scenario_params_fills_defaults_and_rejects_unknown_keys():
    assert scenario_params(_spec())["min_gap_on_gateway"] == DEFAULTS["min_gap_on_gateway"]
    with pytest.raises(ValueError, match="no_such_key"):
        scenario_params(_spec(no_such_key=1))
    with pytest.raises(ValueError, match="matching"):
        scenario_params(_spec(matchings=["sideways"]))


def test_old_scenarios_key_is_rejected_with_a_rename_hint(tmp_path):
    path = tmp_path / "exp.json"
    path.write_text(json.dumps({"name": "demo", "location": LOCATION, "scenarios": {}}))

    with pytest.raises(ValueError, match='renamed to "scenario_config"'):
        experiment_spec.load(path)


def test_sweep_and_by_size_order_instances_by_train_count():
    configs = run_experiment._sweep(_spec(number_of_trains=[9, 1, 4], matchings=["FIFO"],
                                          number_of_instances=1))

    assert run_experiment._by_size(configs) == [
        "custom_1_FIFO_0", "custom_4_FIFO_0", "custom_9_FIFO_0"]
    assert run_experiment._scenario_path(Path("/r"), "custom_1_FIFO_0") == (
        Path("/r/custom_1_FIFO_0/scenario_custom_1_FIFO_0.json"))


def test_report_finds_the_scenario_in_the_instance_dir(tmp_path):
    instance_dir = tmp_path / "custom_2_FIFO_0"
    tool_dir = instance_dir / "local_search" / "seed1"
    tool_dir.mkdir(parents=True)
    (instance_dir / "scenario_custom_2_FIFO_0.json").write_text(json.dumps({"endTime": 5}))

    eval_result = {"location": LOCATION, "scenario": "scenario_custom_2_FIFO_0.json"}
    assert _scenario_for(eval_result, tool_dir) == {"endTime": 5}


def test_departure_delay_reads_the_given_scenario(tmp_path):
    scenario = tmp_path / "scenario_x.json"
    scenario.write_text(json.dumps({"startTime": 0, "endTime": 1000}))

    assert run_experiment._departure_delay(scenario, 0.5) == 500
    assert run_experiment._departure_delay(scenario, 0) is None
    assert run_experiment._departure_delay(tmp_path / "missing.json", 0.5) is None


def _dry_run(script: str, *args: str) -> str:
    result = subprocess.run([sys.executable, str(ROOT / script), "--dry-run", *args],
                            cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_generator_experiment_mode_keeps_no_config_files(tmp_path):
    experiment = tmp_path / "exp.json"
    experiment.write_text(json.dumps(_spec(number_of_trains=[2], matchings=["FIFO"],
                                           number_of_instances=1)))
    run_dir = tmp_path / "run"

    out = _dry_run("run_generator.py", "--experiment", str(experiment), "--run-dir", str(run_dir))

    assert f"source={(run_dir / 'custom_2_FIFO_0').resolve()},target=/app/run" in out
    assert "--config /app/config/scenario_config_custom_2_FIFO_0.json" in out
    assert "--scenario-file /app/run/scenario_custom_2_FIFO_0.json" in out
    # The expanded configs lived in a temporary directory, and a dry run writes nothing.
    assert not run_dir.exists()


@pytest.mark.parametrize("script", ["run_solver.py", "run_planner.py"])
def test_tools_mount_a_scenario_outside_the_location(tmp_path, script):
    scenario = tmp_path / "custom_2_FIFO_0" / "scenario_custom_2_FIFO_0.json"
    scenario.parent.mkdir()
    scenario.write_text("{}")

    out = _dry_run(script, "--location", LOCATION, "--scenario", str(scenario),
                   "--output-dir", str(tmp_path / "out"))

    assert str(scenario.parent.resolve()) in out and "/app/scenario" in out


def test_evaluator_mounts_a_scenario_outside_the_location(tmp_path):
    scenario = tmp_path / "scenario_custom_2_FIFO_0.json"
    scenario.write_text("{}")

    out = _dry_run("run_evaluator.py", "--location", LOCATION, "--scenario", str(scenario),
                   "--plan", str(tmp_path / "local_search" / "plan.json"))

    assert "--path_scenario /app/scenario/scenario_custom_2_FIFO_0.json" in out
