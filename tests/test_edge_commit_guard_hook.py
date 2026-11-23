"""Behaviour of .githooks/pre-commit in a throwaway git repo: it must refuse a direct commit to edge but let a
`git merge --no-ff` finish, including one that stopped on a conflict and is concluded with `git commit` (issue #42)."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / ".githooks" / "pre-commit"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not available")


def git(repo, *args, check=True):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    return subprocess.run(["git", *args], cwd=repo, env=env, check=check, capture_output=True, text=True)


def commit_file(repo, name, text, message):
    (repo / name).write_text(text)
    git(repo, "add", name)
    return git(repo, "commit", "-m", message, check=False)


@pytest.fixture
def repo(tmp_path):
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    shutil.copy(HOOK, hooks / "pre-commit")
    r = tmp_path / "r"
    r.mkdir()
    git(r, "init", "-b", "main")
    git(r, "config", "core.hooksPath", str(hooks))
    assert commit_file(r, "f.txt", "base\n", "base").returncode == 0  # on main: allowed
    git(r, "branch", "edge")
    return r


def test_direct_commit_to_edge_is_refused(repo):
    git(repo, "checkout", "edge")
    result = commit_file(repo, "f.txt", "direct\n", "direct")
    assert result.returncode != 0
    assert "refusing to commit directly to 'edge'" in result.stderr


def test_commit_on_feature_branch_is_allowed(repo):
    git(repo, "checkout", "-b", "feature")
    assert commit_file(repo, "f.txt", "feature\n", "feature").returncode == 0


def test_clean_no_ff_merge_into_edge_is_allowed(repo):
    git(repo, "checkout", "-b", "feature")
    commit_file(repo, "g.txt", "g\n", "feature")
    git(repo, "checkout", "edge")
    assert git(repo, "merge", "--no-ff", "-m", "merge", "feature", check=False).returncode == 0


def test_conflicted_no_ff_merge_can_be_concluded_on_edge(repo):
    git(repo, "checkout", "-b", "feature")
    commit_file(repo, "f.txt", "feature\n", "feature")
    git(repo, "checkout", "main")
    commit_file(repo, "f.txt", "main\n", "main")
    git(repo, "branch", "-f", "edge", "main")
    git(repo, "checkout", "edge")
    assert git(repo, "merge", "--no-ff", "feature", check=False).returncode != 0  # conflict
    (repo / "f.txt").write_text("resolved\n")
    git(repo, "add", "f.txt")
    assert git(repo, "commit", "--no-edit", check=False).returncode == 0
    # ...and the very next, ordinary commit is refused again.
    assert commit_file(repo, "f.txt", "after\n", "after").returncode != 0
