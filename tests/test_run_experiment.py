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


def test_max_duration_lifts_the_solver_iteration_cap():
    from run_solver import UNCAPPED_ITERATIONS, _apply_overrides

    old_schema = {"SimulatedAnnealing": {"IterationsUntilReset": 15000, "Reset": 2000}}
    sa = _apply_overrides(old_schema, 300, None)["SimulatedAnnealing"]
    assert sa == {"IterationsUntilReset": UNCAPPED_ITERATIONS, "Reset": 2000, "MaxDuration": 300}

    new_schema = {"SimulatedAnnealing": {"MaxIterations": 15000, "IterationsUntilReset": 2000}}
    sa = _apply_overrides(new_schema, 300, None)["SimulatedAnnealing"]
    assert sa["MaxIterations"] == UNCAPPED_ITERATIONS and sa["IterationsUntilReset"] == 2000

    untouched = {"SimulatedAnnealing": {"IterationsUntilReset": 15000, "Reset": 2000}}
    assert _apply_overrides(untouched, None, None)["SimulatedAnnealing"]["IterationsUntilReset"] == 15000


def test_length_fill_is_all_units_over_parking_length(tmp_path):
    from scripts.report_results import instance_feasibility, length_fill

    scenario = {
        "trainUnitTypes": [{"typePrefix": "A", "carriages": 4, "length": 100.0},
                           {"typePrefix": "B", "carriages": 3, "length": 50.0}],
        "in": [{"members": [{"typePrefix": "A", "carriages": 4},
                            {"typePrefix": "B", "carriages": 3}]}],
        "inStanding": [{"members": [{"typePrefix": "B", "carriages": 3}]}],
    }
    location = {"trackParts": [
        {"type": "RailRoad", "parkingAllowed": True, "length": 300.0},
        {"type": "RailRoad", "parkingAllowed": True, "length": 100.0},
        {"type": "RailRoad", "parkingAllowed": False, "length": 999.0},
        {"type": "Switch", "parkingAllowed": True, "length": 999.0},
    ]}
    assert length_fill(scenario, location) == 0.5  # (100 + 50 + 50) / (300 + 100)
    assert length_fill({**scenario, "trainUnitTypes": []}, location) is None

    # In run_experiment's layout the location comes from the run's experiment.json.
    instance_dir = tmp_path / "custom_2_FIFO_0"
    instance_dir.mkdir()
    (tmp_path / "experiment.json").write_text(json.dumps({"location": LOCATION}))
    (instance_dir / "scenario_custom_2_FIFO_0.json").write_text(json.dumps(scenario))
    row = instance_feasibility("custom_2_FIFO_0", instance_dir, 1800)
    assert 0 < row["length_fill"] < 1


def test_generated_scenario_is_reused_only_for_the_same_image_and_config(tmp_path):
    from run_generator import _generation_stamp, _stamp_path, _up_to_date

    instance = "custom_2_FIFO_0"
    config = {"number_of_trains": 2, "seed": 42}
    stamp = _generation_stamp("generator:latest", "sha256:aaa", config)
    (tmp_path / f"scenario_{instance}.json").write_text("{}")

    assert not _up_to_date(tmp_path, instance, stamp)  # no stamp yet
    _stamp_path(tmp_path, instance).write_text(json.dumps(stamp))
    assert _up_to_date(tmp_path, instance, stamp)

    rebuilt = _generation_stamp("generator:latest", "sha256:bbb", config)
    assert not _up_to_date(tmp_path, instance, rebuilt)
    other_config = _generation_stamp("generator:latest", "sha256:aaa", {**config, "seed": 43})
    assert not _up_to_date(tmp_path, instance, other_config)
    unknown_image = _generation_stamp("generator:latest", None, config)
    assert not _up_to_date(tmp_path, instance, unknown_image)

    (tmp_path / f"scenario_{instance}.json").unlink()
    assert not _up_to_date(tmp_path, instance, stamp)  # stamp without its scenario


def test_attempts_are_reused_until_an_input_changes(tmp_path, monkeypatch):
    calls = {"tool": 0, "eval": 0}
    ids = {"run_solver.py": "sha256:solver-1", "run_evaluator.py": "sha256:eval-1"}

    def fake_tool(tool, location, instance, scenario, tool_dir, *args, **kwargs):
        calls["tool"] += 1
        tool_dir.mkdir(parents=True, exist_ok=True)
        (tool_dir / "plan.json").write_text('{"actions": []}')
        result = {"plan_produced": True, "exit_code": 0, "timed_out": False, "wall_seconds": 1.0}
        (tool_dir / "result.json").write_text(json.dumps(result))
        return result

    def fake_eval(location, instance, scenario, plan, *args, **kwargs):
        calls["eval"] += 1
        result = {"solved": True, "verdict": "accepted", "reason": ""}
        (plan.parent / "eval_result.json").write_text(json.dumps(result))
        return result

    monkeypatch.setattr(run_experiment, "_run_tool", fake_tool)
    monkeypatch.setattr(run_experiment, "_run_evaluator", fake_eval)
    monkeypatch.setattr(run_experiment, "_image_id",
                        lambda engine, image, cache_dir: ids["run_evaluator.py" if "tors" in image else "run_solver.py"])

    scenario = tmp_path / "scenario_custom_2_FIFO_0.json"
    scenario.write_text(json.dumps({"startTime": 0, "endTime": 100}))
    tool_dir = tmp_path / "custom_2_FIFO_0" / "local_search" / "seed1"

    def attempt():
        return run_experiment._run_and_record(
            "solver", LOCATION, "custom_2_FIFO_0", scenario, tool_dir, "edge", "edge", "edge",
            False, 60, 1, "symbolic-rail", 0.0, {}, "solver_seed1")

    assert attempt() and calls == {"tool": 1, "eval": 1}
    assert attempt() and calls == {"tool": 1, "eval": 1}  # everything reused

    ids["run_evaluator.py"] = "sha256:eval-2"  # new evaluator image: re-evaluate only
    assert attempt() and calls == {"tool": 1, "eval": 2}

    ids["run_solver.py"] = "sha256:solver-2"  # new solver image: rerun everything
    assert attempt() and calls == {"tool": 2, "eval": 3}

    scenario.write_text(json.dumps({"startTime": 0, "endTime": 200}))  # regenerated scenario
    assert attempt() and calls == {"tool": 3, "eval": 4}


def test_interrupted_attempts_are_not_reused():
    assert run_experiment._reusable({"exit_code": 0})
    assert run_experiment._reusable({"exit_code": 1})  # the tool's own failure is an outcome
    assert run_experiment._reusable({"exit_code": 137, "timed_out": True})  # its budget ran out
    assert not run_experiment._reusable({"exit_code": 137, "timed_out": False})  # killed from outside
    assert not run_experiment._reusable({"exit_code": None})
    assert not run_experiment._reusable({})


def test_both_docker_desktop_mount_race_messages_are_recognised():
    from scripts.docker_utils import _failed_bind_source

    old = "docker: Error response from daemon: bind source path does not exist: /host_mnt/Users/x/results/a"
    new = ('docker: Error response from daemon: invalid mount config for type "bind": '
           "stat /host_mnt/Users/x/results/b: operation not permitted")
    assert _failed_bind_source(old) == Path("/Users/x/results/a")
    assert _failed_bind_source(new) == Path("/Users/x/results/b")
    assert _failed_bind_source("docker: some other error") is None
