"""Tests for scripts/check_push_script_sync.py, on small fake repo trees (not the real sibling repos)."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "check_push_script_sync", Path(__file__).resolve().parents[1] / "scripts" / "check_push_script_sync.py"
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

SCRIPTS = [("a/push.sh", ("one", "two")), ("b/sub/push.sh", ("one", "two"))]


def script(one="echo 1", two="echo 2", head="echo a"):
    return f"""#!/usr/bin/env bash
{head}
# BEGIN SHARED BLOCK: one (hint, may differ per copy {head})
{one}
# END SHARED BLOCK: one
IMAGE=whatever-{head}
# BEGIN SHARED BLOCK: two
{two}
# END SHARED BLOCK: two
"""


def write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_identical_blocks_pass_even_if_rest_and_marker_hint_differ(tmp_path):
    write(tmp_path, "a/push.sh", script(head="A"))
    write(tmp_path, "b/sub/push.sh", script(head="B"))
    assert mod.check(tmp_path, SCRIPTS) == []


def test_drifted_block_is_reported_with_a_diff(tmp_path):
    write(tmp_path, "a/push.sh", script())
    write(tmp_path, "b/sub/push.sh", script(one="echo CHANGED"))
    problems = mod.check(tmp_path, SCRIPTS)
    assert len(problems) == 1
    assert "'one' differs between a/push.sh and b/sub/push.sh" in problems[0]
    assert "-echo 1" in problems[0] and "+echo CHANGED" in problems[0]


def test_missing_block_is_reported(tmp_path):
    write(tmp_path, "a/push.sh", script())
    write(
        tmp_path, "b/sub/push.sh", "#!/usr/bin/env bash\n# BEGIN SHARED BLOCK: one\necho 1\n# END SHARED BLOCK: one\n"
    )
    assert mod.check(tmp_path, SCRIPTS) == ["b/sub/push.sh: missing shared block 'two'"]


def test_missing_file_is_reported(tmp_path):
    write(tmp_path, "a/push.sh", script())
    assert mod.check(tmp_path, SCRIPTS) == [f"b/sub/push.sh: not found under {tmp_path}"]


@pytest.mark.parametrize(
    "text, fragment",
    [
        ("# BEGIN SHARED BLOCK: one\necho 1\n", "has no END marker"),
        ("# BEGIN SHARED BLOCK: one\n# BEGIN SHARED BLOCK: two\n# END SHARED BLOCK: two\n", "begins inside block"),
        (
            "# BEGIN SHARED BLOCK: one\n# END SHARED BLOCK: one\n# BEGIN SHARED BLOCK: one\n# END SHARED BLOCK: one\n",
            "more than once",
        ),
        ("# END SHARED BLOCK: one\n", "does not match open block"),
    ],
)
def test_malformed_markers_are_reported(tmp_path, text, fragment):
    problems = []
    mod.extract_blocks(text, "x.sh", problems)
    assert any(fragment in p for p in problems), problems


def test_real_script_list_covers_all_repos():
    repos = {rel.split("/")[0] for rel, _ in mod.SCRIPTS}
    assert repos == {
        "robust-rail-evaluator",
        "robust-rail-planner",
        "robust-rail-solver",
        "robust-rail-generator",
        "robust-rail-general",
    }


def test_own_repo_is_resolved_against_self_root_not_root(tmp_path):
    root, own = tmp_path / "root", tmp_path / "checkout-with-another-name"
    write(root, "a/push.sh", script())
    write(own, "push.sh", script())
    scripts = [("a/push.sh", ("one", "two")), (f"{mod.SELF_REPO}/push.sh", ("one", "two"))]
    assert mod.check(root, scripts, self_root=own) == []
    write(own, "push.sh", script(two="echo CHANGED"))
    assert "'two' differs" in mod.check(root, scripts, self_root=own)[0]


def test_real_script_list_covers_the_edge_commit_guard_in_every_repo():
    guarded = {rel.split("/")[0] for rel, blocks in mod.SCRIPTS if "edge-commit-guard" in blocks}
    assert guarded == {rel.split("/")[0] for rel, _ in mod.SCRIPTS}
