"""Tests for the Issa-grid tooling in experiments/issa-grid/: extract_csv.py (outcome classification, the
tasks.tsv and sacct joins) and submit_grid.sh (task selection, manifest pruning, stage reuse, partition check).

Neither needs a cluster: submit_grid.sh runs with DRY=1 and a fake `sinfo`, so no `sbatch` is called.
"""
import csv
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GRID = REPO / "experiments" / "issa-grid"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, GRID / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


extract_csv = _load("extract_csv")


# ---------------------------------------------------------------- extract_csv.py

def _write(path, content=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content))


def _task_dir(run, instance, folder, result=None, eval_solved=None, eval_reason="", plan_actions=None, out="", err="",
              solver_out=None):
    d = run / instance / folder
    d.mkdir(parents=True, exist_ok=True)
    if result is not None:
        _write(d / "result.json", result)
    if eval_solved is not None:
        _write(d / "eval_result.json", {"solved": eval_solved, "reason": eval_reason})
    if plan_actions is not None:
        _write(d / "plan.json", {"actions": [{}] * plan_actions})
    if out:
        _write(d / "planner.out", out)
    if err:
        _write(d / "planner.err", err)
    if solver_out is not None:
        _write(d / "solver.out", solver_out)
    return d


@pytest.fixture
def run_dir(tmp_path):
    run = tmp_path / "run"
    rows = [
        (0, "custom_3_FIFO_0", "solver", "", "custom_3_FIFO_0/local_search"),
        (1, "custom_3_FIFO_0", "planner", "enhsp", "custom_3_FIFO_0/planning-enhsp"),
        (2, "custom_3_FIFO_0", "planner", "symbolic-rail", "custom_3_FIFO_0/planning-symbolic-rail"),
        (3, "custom_1_FIFO_0", "solver", "", "custom_1_FIFO_0/local_search"),
        (4, "custom_3_FIFO_1", "planner", "symbolic-rail", "custom_3_FIFO_1/planning-symbolic-rail"),
    ]
    _write(run / "tasks.tsv", "index\tinstance\ttool\tplanner\tseed\ttool_dir\n"
           + "".join(f"{i}\t{inst}\t{tool}\t{planner}\t\t{d}\n" for i, inst, tool, planner, d in rows))
    # task 0: solver, valid; first line of solver.out is the build, the last line the machine-readable stats
    _task_dir(run, "custom_3_FIFO_0", "local_search",
              result={"wall_seconds": 1.5, "timed_out": False, "exit_code": 0, "plan_produced": True,
                      "image": "ghcr.io/robust-rail-nl/hip:edge"},
              eval_solved=True, plan_actions=11,
              solver_out="HIP 2.2.0-edge+20261106.965fd71\nSTATS search_seconds=1.20 neighbors=91 iterations=3 "
                         "feasible=true time_to_best_seconds=0.61\n")
    # task 1: enhsp, hit the budget with no plan
    _task_dir(run, "custom_3_FIFO_0", "planning-enhsp",
              result={"wall_seconds": 1800.0, "timed_out": True, "exit_code": None, "plan_produced": False,
                      "planner_impl": "enhsp"},
              out="TIMING stage=pddl_conversion seconds=0.5\n", err="robust-rail-planner 0.5.0-edge+20261106.2f2f34b\n")
    # task 2: symbolic-rail, plan produced but rejected by the evaluator
    _task_dir(run, "custom_3_FIFO_0", "planning-symbolic-rail",
              result={"wall_seconds": 20.0, "timed_out": False, "exit_code": 0, "plan_produced": True,
                      "planner_impl": "symbolic-rail"},
              eval_solved=False, eval_reason="plan rejected", plan_actions=12,
              out="TIMING stage=pddl_conversion seconds=0.3\nTIMING stage=search seconds=5.2\n"
                  "TIMING stage=planner_process seconds=12.9\nTIMING stage=json_conversion seconds=0.01\n"
                  "STATS expanded=16 plan_length=10\nTIMING stage=total seconds=16.1\n")
    # task 3: the generator refused the scenario: only its stderr exists
    _write(run / "custom_1_FIFO_0" / "scenario_custom_1_FIFO_0.err", "ERROR: no time to park and service\n")
    # task 4: the scenario exists but the task was killed before writing result.json
    _write(run / "custom_3_FIFO_1" / "scenario_custom_3_FIFO_1.json", {})
    _write(run / "custom_3_FIFO_0" / "scenario_custom_3_FIFO_0.json", {})
    return run


SACCT = """\
77_0|daic-eemcs-st|gpu52|00:00:02||COMPLETED
77_0.batch|daic-eemcs-st|gpu52|00:00:02|185552K|COMPLETED
77_0.extern|daic-eemcs-st|gpu52|00:00:02||COMPLETED
77_4|daic-eemcs-st|gpu49|00:21:00||OUT_OF_MEMORY
77_4.batch|daic-eemcs-st|gpu49|00:21:00|3994120K|OUT_OF_MEMORY
88_[0-5]|daic-eemcs-st||00:00:00||PENDING
"""


def _extract(tmp_path, run, sacct=None, ids="77"):
    out = tmp_path / "out.csv"
    cmd = [sys.executable, str(GRID / "extract_csv.py"), "--run", f"on={run}:{ids}", "-o", str(out)]
    if sacct:
        _write(tmp_path / "sacct.txt", sacct)
        cmd += ["--sacct", str(tmp_path / "sacct.txt")]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    with open(out, newline="") as f:
        return {(r["type-solver"], r["num_trains"], r["instance-num"]): r for r in csv.DictReader(f)}


def test_every_task_gets_a_row_with_the_right_outcome(tmp_path, run_dir):
    rows = _extract(tmp_path, run_dir, SACCT)

    assert len(rows) == 5
    assert rows[("solver", "3", "0")]["outcome"] == "valid"
    assert rows[("enhsp", "3", "0")]["outcome"] == "timeout"
    assert rows[("symbolic-rail", "3", "0")]["outcome"] == "invalid"
    assert rows[("symbolic-rail", "3", "0")]["reason"] == "plan rejected"
    assert rows[("solver", "1", "0")]["outcome"] == "no_scenario"
    # killed before result.json: only sacct knows why
    assert rows[("symbolic-rail", "3", "1")]["outcome"] == "oom"


def test_without_sacct_a_missing_result_is_no_result_not_a_dropped_row(tmp_path, run_dir):
    rows = _extract(tmp_path, run_dir)

    assert rows[("symbolic-rail", "3", "1")]["outcome"] == "no_result"
    assert len(rows) == 5


def test_sacct_join_adds_node_partition_and_peak_memory(tmp_path, run_dir):
    rows = _extract(tmp_path, run_dir, SACCT)

    oom = rows[("symbolic-rail", "3", "1")]
    assert (oom["node"], oom["partition"], oom["slurm_state"]) == ("gpu49", "daic-eemcs-st", "OUT_OF_MEMORY")
    assert float(oom["maxrss_mb"]) == pytest.approx(3994120 / 1024, abs=0.1)
    # a pending array line ("88_[0-5]") and the .extern step must not produce entries or errors
    assert float(rows[("solver", "3", "0")]["maxrss_mb"]) == pytest.approx(185552 / 1024, abs=0.1)


def test_planner_stage_lines_and_solver_stats_are_parsed(tmp_path, run_dir):
    rows = _extract(tmp_path, run_dir)

    sym = rows[("symbolic-rail", "3", "0")]
    assert (sym["pddl_conversion_s"], sym["search_s"], sym["planner_process_s"]) == ("0.3", "5.2", "12.9")
    assert (sym["expanded-states"], sym["solution-length"], sym["json_actions"]) == ("16", "10", "12")
    solver = rows[("solver", "3", "0")]
    assert (solver["solver_neighbors"], solver["time_to_best_s"], solver["solver_feasible"]) == ("91", "0.61", "true")
    assert solver["solution-length"] == "11"          # the solver's length is the JSON action count
    assert solver["build"] == "HIP 2.2.0-edge+20261106.965fd71"
    assert rows[("enhsp", "3", "0")]["build"] == "robust-rail-planner 0.5.0-edge+20261106.2f2f34b"


# ---------------------------------------------------------------- submit_grid.sh

def _experiment(tmp_path):
    spec = {
        "name": "grid_test", "location": "Location_KleineBinckhorst", "tools": ["solver", "planner"],
        "planner": ["enhsp", "symbolic-rail"], "max_duration": 60, "jobs": 1,
        "versions": {"generator": "edge", "solver": "edge", "planner": "edge", "evaluator": "edge"},
        "scenario_config": {"number_of_trains": [1, 2, 3], "number_of_instances": 2, "matchings": ["FIFO"], "seed": 1,
                            "perform_servicing": False},
    }
    path = tmp_path / "grid_test.json"
    path.write_text(json.dumps(spec))
    return path


def _submit(tmp_path, exp, out, env_extra=None, site="daic", sinfo_has="daic-eemcs-st"):
    """Run submit_grid.sh with DRY=1 and a fake sinfo; return (completed process, {class: [array indices]})."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "sinfo"
    fake.write_text(f'#!/bin/bash\n[ "$3" = "{sinfo_has}" ] && echo up\nexit 0\n')
    fake.chmod(0o755)
    env = dict(os.environ, DRY="1", HOME=str(tmp_path / "home"),
               PATH=os.pathsep.join([str(bin_dir), str(Path(sys.executable).parent), os.environ["PATH"]]))
    env.pop("SLURM_SITE", None)
    if site:
        env["SLURM_SITE"] = site
    env.update(env_extra or {})
    (tmp_path / "home").mkdir(exist_ok=True)
    proc = subprocess.run(["bash", str(GRID / "submit_grid.sh"), str(exp), str(out), str(tmp_path / "dest")],
                          cwd=REPO, env=env, capture_output=True, text=True)
    arrays = {}
    for line in proc.stderr.splitlines():
        m = re.search(r"--job-name=issa-(\S+).*--array=(\S+)%", line)
        if m:
            indices = []
            for part in m[2].split(","):
                lo, _, hi = part.partition("-")
                indices += range(int(lo), int(hi or lo) + 1)
            arrays[m[1]] = indices
    return proc, arrays


def _tasks(out):
    with open(out / "tasks.tsv", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def test_all_tasks_are_submitted_by_default_hardest_first(tmp_path):
    out = tmp_path / "out"
    proc, arrays = _submit(tmp_path, _experiment(tmp_path), out)

    assert proc.returncode == 0, proc.stderr
    assert {k: len(v) for k, v in arrays.items()} == {"solver": 6, "enhsp": 6, "symbolic-rail": 6}
    assert sorted(sum(arrays.values(), [])) == list(range(18))
    trains = [int(re.match(r"custom_(\d+)_", r["instance"])[1]) for r in _tasks(out)]
    assert trains == sorted(trains, reverse=True)          # 3-train scenarios take the lowest indices


def test_train_and_instance_filters_pick_the_right_tasks(tmp_path):
    out = tmp_path / "out"
    _, arrays = _submit(tmp_path, _experiment(tmp_path), out,
                        {"TRAINS_MIN": "2", "TRAINS_MAX": "3", "INSTANCE_MIN": "1", "ENHSP_TRAINS_MAX": "2"})

    by_index = {int(r["index"]): r for r in _tasks(out)}
    picked = {tool: [by_index[i]["instance"] for i in idx] for tool, idx in arrays.items()}
    assert sorted(picked["solver"]) == ["custom_2_FIFO_1", "custom_3_FIFO_1"]
    assert picked["enhsp"] == ["custom_2_FIFO_1"]                       # capped at 2 trains
    assert sorted(picked["symbolic-rail"]) == ["custom_2_FIFO_1", "custom_3_FIFO_1"]


def test_prune_manifest_keeps_only_the_selection_numbered_from_zero(tmp_path):
    out = tmp_path / "out"
    _, arrays = _submit(tmp_path, _experiment(tmp_path), out,
                        {"PRUNE_MANIFEST": "1", "TRAINS_MIN": "2", "INSTANCE_MIN": "1", "ENHSP_TRAINS_MAX": "2"})

    rows = _tasks(out)
    assert len(rows) == 5                                             # solver 2 + enhsp 1 + symbolic-rail 2
    assert [int(r["index"]) for r in rows] == list(range(5))          # below SLURM's MaxArraySize
    assert sorted(sum(arrays.values(), [])) == list(range(5))


def test_a_later_stage_reuses_tasks_tsv_and_skips_generation(tmp_path):
    out = tmp_path / "out"
    _submit(tmp_path, _experiment(tmp_path), out, {"TRAINS_MAX": "2"})
    before = (out / "tasks.tsv").read_bytes()
    mtime = (out / "tasks.tsv").stat().st_mtime_ns
    time.sleep(0.05)

    proc, arrays = _submit(tmp_path, _experiment(tmp_path), out, {"TRAINS_MIN": "3", "SKIP_GENERATE": "1"})

    assert (out / "tasks.tsv").read_bytes() == before
    # a rebuild gives the same bytes, but writes the file in the manifest's own order for a moment first, and an array
    # task starting then would read the wrong row: so the file must not be touched at all
    assert (out / "tasks.tsv").stat().st_mtime_ns == mtime
    assert "reusing existing" in proc.stdout
    assert "generate_scenarios.sbatch" not in proc.stderr
    assert "--dependency=afterok" not in proc.stderr                  # the arrays have nothing to wait for
    assert {k: len(v) for k, v in arrays.items()} == {"solver": 2, "enhsp": 2, "symbolic-rail": 2}


def test_gen_dep_afterany_lets_arrays_start_after_a_failed_generate(tmp_path):
    proc, _ = _submit(tmp_path, _experiment(tmp_path), tmp_path / "out", {"GEN_DEP": "afterany"})

    assert "--dependency=afterany:0" in proc.stderr
    assert "--dependency=afterok" not in proc.stderr


def test_a_partition_the_cluster_does_not_have_stops_before_any_submission(tmp_path):
    # the site defaults to delftblue (compute-p1); this fake cluster only has daic-eemcs-st
    proc, arrays = _submit(tmp_path, _experiment(tmp_path), tmp_path / "out", site=None)

    assert proc.returncode == 1
    assert "no partition 'compute-p1'" in proc.stderr
    assert "[dry] sbatch" not in proc.stderr and arrays == {}


def test_grid_jobs_file_is_appended_to_not_truncated(tmp_path):
    out = tmp_path / "out"
    _submit(tmp_path, _experiment(tmp_path), out, {"TRAINS_MAX": "2"})
    _submit(tmp_path, _experiment(tmp_path), out, {"TRAINS_MIN": "3", "SKIP_GENERATE": "1"})

    stages = [line for line in (out / "grid_jobs.txt").read_text().splitlines() if line.startswith("#")]
    assert len(stages) == 2
