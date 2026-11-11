"""Tests for --single: the exactly-one selection check, folding --single into
--instance, and the tee in docker_utils.run_container (console echo in addition
to the .out/.err files, stderr colored only on a terminal)."""

import argparse
import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import docker_utils
from scripts.docker_utils import _pump, run_container
from scripts.instance_filter import add_single_arg, apply_single, ensure_single

ROOT = Path(__file__).resolve().parent.parent
PY_BOTH = [sys.executable, "-c",
           "import sys; print('to-stdout'); print('to-stderr', file=sys.stderr)"]


def _paths(tmp_path: Path, *names: str) -> list[Path]:
    return [tmp_path / f"scenario_{n}.json" for n in names]


def test_ensure_single_accepts_exactly_one(tmp_path):
    ensure_single(_paths(tmp_path, "a", "b"), "a", "scenario_")
    ensure_single(_paths(tmp_path, "a", "b"), "b*", "scenario_")  # wildcard resolving to one


def test_ensure_single_rejects_no_match(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        ensure_single(_paths(tmp_path, "a", "b"), "zzz", "scenario_")
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "--single 'zzz' matched no files" in err
    assert "Available instances" in err


def test_ensure_single_rejects_several_and_lists_them(tmp_path, capsys):
    loc1, loc2 = tmp_path / "Location_A", tmp_path / "Location_B"
    paths = [loc1 / "scenario_x.json", loc2 / "scenario_x.json", loc1 / "scenario_y.json"]
    with pytest.raises(SystemExit) as exc:
        ensure_single(paths, "x", "scenario_")  # same name in two locations
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "matched 2 files" in err
    assert str(paths[0]) in err and str(paths[1]) in err


def _parsed(argv: list[str]):
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance")
    add_single_arg(parser, "scenario")
    args = parser.parse_args(argv)
    apply_single(parser, args)
    return args


def test_apply_single_folds_into_instance_and_tees():
    args = _parsed(["--single", "foo"])
    assert (args.instance, args.tee) == ("foo", True)


def test_apply_single_absent_leaves_instance_quiet():
    args = _parsed(["--instance", "foo"])
    assert (args.instance, args.tee) == ("foo", False)


def test_apply_single_excludes_instance():
    with pytest.raises(SystemExit):
        _parsed(["--single", "a", "--instance", "b"])


def test_run_container_tee_echoes_and_still_writes_files(tmp_path, capfd):
    out, err = tmp_path / "t.out", tmp_path / "t.err"
    returncode, timed_out = run_container(PY_BOTH, "x", out, err, 30, "apptainer", tee=True)

    assert (returncode, timed_out) == (0, False)
    assert out.read_text() == "to-stdout\n"
    assert err.read_text() == "to-stderr\n"
    console = capfd.readouterr()
    assert console.out == "to-stdout\n"
    assert console.err == "to-stderr\n"  # no color: not a terminal


def test_run_container_without_tee_keeps_console_quiet(tmp_path, capfd):
    out, err = tmp_path / "t.out", tmp_path / "t.err"
    run_container(PY_BOTH, "x", out, err, 30, "apptainer")

    assert out.read_text() == "to-stdout\n"
    assert err.read_text() == "to-stderr\n"
    console = capfd.readouterr()
    assert console.out == "" and console.err == ""


class _FakeTty(io.StringIO):
    def isatty(self):
        return True


def _pump_bytes(data: bytes, console, color, tmp_path):
    r, w = os.pipe()
    os.write(w, data)
    os.close(w)
    with os.fdopen(r, "rb") as source, open(tmp_path / "f", "wb") as file:
        _pump(source, file, console, color)
    return (tmp_path / "f").read_bytes()


def test_pump_colors_console_copy_only_on_a_terminal(tmp_path, monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm")
    console = _FakeTty()
    saved = _pump_bytes(b"oops\n", console, docker_utils.STDERR_COLOR, tmp_path)

    assert saved == b"oops\n"  # the file never gets escape codes
    assert console.getvalue() == "\x1b[91moops\n\x1b[0m"


def test_pump_no_color_when_no_color_set_or_not_a_tty(tmp_path, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    console = _FakeTty()
    _pump_bytes(b"oops\n", console, docker_utils.STDERR_COLOR, tmp_path)
    assert console.getvalue() == "oops\n"

    monkeypatch.delenv("NO_COLOR")
    plain = io.StringIO()
    _pump_bytes(b"oops\n", plain, docker_utils.STDERR_COLOR, tmp_path)
    assert plain.getvalue() == "oops\n"


@pytest.mark.parametrize("script", ["run_solver.py", "run_planner.py", "run_generator.py",
                                    "run_evaluator.py"])
def test_scripts_refuse_a_single_that_matches_nothing_before_running(script):
    result = subprocess.run(
        [sys.executable, str(ROOT / script), "--single", "no_such_instance_xyz", "--dry-run"],
        capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 1
    assert "--single 'no_such_instance_xyz' matched no files" in result.stderr


def test_script_refuses_a_single_that_matches_several():
    result = subprocess.run(
        [sys.executable, str(ROOT / "run_solver.py"), "--single", "*", "--dry-run"],
        capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 1
    assert "runs exactly one" in result.stderr
