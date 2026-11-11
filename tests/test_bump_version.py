"""Tests for bump-version.sh, run in a throwaway git repository with a stub `uv` (no network, no real lock).

The stub's `lock` rewrites the version of the robust-rail-general entry in uv.lock to match pyproject.toml,
which is what the real `uv lock` does for this package.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "bump-version.sh"

PYPROJECT = '[project]\nname = "robust-rail-general"\nversion = "0.3.0"\n'
LOCK = '[[package]]\nname = "robust-rail-general"\nversion = "0.1.1"\nsource = { editable = "." }\n'
STUB_UV = """#!/usr/bin/env bash
[[ "$1" == "lock" ]] || exit 2
v=$(sed -n 's:^version = "\\(.*\\)"$:\\1:p' pyproject.toml)
sed -i "s#^version = \\".*\\"\\$#version = \\"$v\\"#" uv.lock
"""


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    (stub_dir / "uv").write_text(STUB_UV)
    (stub_dir / "uv").chmod(0o755)
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.email", "t@example.org")
    git(r, "config", "user.name", "T")
    (r / "pyproject.toml").write_text(PYPROJECT)
    (r / "uv.lock").write_text(LOCK)
    shutil.copy(SCRIPT, r / "bump-version.sh")
    git(r, "add", "pyproject.toml", "uv.lock", "bump-version.sh")
    git(r, "commit", "-q", "-m", "init")
    monkeypatch.setenv("PATH", f"{stub_dir}:{os.environ['PATH']}")
    return r


def bump(repo, *args):
    return subprocess.run(["bash", "bump-version.sh", *args], cwd=repo, capture_output=True, text=True)


@pytest.mark.parametrize("arg,new", [("patch", "0.3.1"), ("minor", "0.4.0"), ("major", "1.0.0"), ("0.7.2", "0.7.2")])
def test_bump_commits_pyproject_and_lock_and_tags(repo, arg, new):
    res = bump(repo, arg)
    assert res.returncode == 0, res.stderr
    assert f'version = "{new}"' in (repo / "pyproject.toml").read_text()
    assert f'version = "{new}"' in (repo / "uv.lock").read_text()
    assert git(repo, "log", "-1", "--format=%s") == f"Bump version to {new}"
    assert set(git(repo, "show", "--name-only", "--format=", "HEAD").split()) == {"pyproject.toml", "uv.lock"}
    assert git(repo, "tag", "--list") == f"v{new}"
    assert git(repo, "status", "--porcelain") == ""


def test_untracked_file_blocks_the_bump(repo):
    (repo / "results.csv").write_text("x\n")
    res = bump(repo, "patch")
    assert res.returncode == 1
    assert "not clean" in res.stderr
    assert git(repo, "tag", "--list") == ""


def test_modified_tracked_file_blocks_the_bump(repo):
    (repo / "uv.lock").write_text(LOCK + "\n")
    res = bump(repo, "patch")
    assert res.returncode == 1
    assert "not clean" in res.stderr
    assert git(repo, "tag", "--list") == ""


def test_existing_tag_blocks_the_bump_before_any_change(repo):
    git(repo, "tag", "v0.3.1")
    res = bump(repo, "patch")
    assert res.returncode == 1
    assert "v0.3.1 already exists" in res.stderr
    assert 'version = "0.3.0"' in (repo / "pyproject.toml").read_text()
    assert git(repo, "status", "--porcelain") == ""


def test_bad_argument_prints_usage(repo):
    res = bump(repo, "banana")
    assert res.returncode == 1
    assert "Usage:" in res.stderr and "Current version: 0.3.0" in res.stderr
