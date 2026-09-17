"""Tests for scripts/sdd/select_tests.py (FEAT-563 TASK-3310)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.sdd.select_tests import main


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=root, check=True, capture_output=True
    )


@pytest.fixture
def fixture_monorepo(tmp_path: Path) -> Path:
    """git-initialised tree: packages/a/{src/pa/x.py,tests/test_x.py}, packages/b/…, tests/test_root.py, pytest.ini."""
    files = {
        "pytest.ini": "[pytest]\n",
        "packages/a/src/pa/x.py": "X = 1\n",
        "packages/a/tests/test_x.py": "def test_x():\n    assert True\n",
        "packages/b/src/pb/y.py": "from pa.x import X\n",
        "packages/b/tests/test_y.py": "def test_y():\n    assert True\n",
        "tests/test_root.py": "def test_root():\n    assert True\n",
    }
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path


def test_cli_json_and_exit_codes(fixture_monorepo, capsys):
    (fixture_monorepo / "packages/a/src/pa/x.py").write_text("X = 2\n")
    rc = main(["--tier", "merge", "--base", "HEAD", "--worktree", str(fixture_monorepo), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tier"] == "merge"
    assert all(len({inv["distribution"]}) == 1 for inv in payload["invocations"])


def test_empty_task_plan_exits_2(fixture_monorepo):
    assert main(["--tier", "task", "--base", "HEAD", "--worktree", str(fixture_monorepo)]) == 2


def test_bad_flag_exits_2():
    assert main(["--tier", "nope"]) == 2


def test_select_tests_on_fixture_monorepo(fixture_monorepo):
    task_file = fixture_monorepo / "task.md"
    task_file.write_text("## Validation Commands\n\n- `pytest packages/a/tests/test_x.py -q`\n")
    (fixture_monorepo / "packages/a/src/pa/x.py").write_text("X = 2\n")

    rc = main(
        ["--tier", "task", "--base", "HEAD", "--worktree", str(fixture_monorepo), "--task-file", "task.md", "--run"]
    )
    assert rc == 0

    (fixture_monorepo / "packages/a/tests/test_x.py").write_text("def test_x():\n    assert False\n")
    rc = main(
        ["--tier", "task", "--base", "HEAD", "--worktree", str(fixture_monorepo), "--task-file", "task.md", "--run"]
    )
    assert rc == 1


def test_run_records_green_core_escalation(fixture_monorepo, capsys, monkeypatch):
    from scripts.sdd.select_tests import _load_kernel

    _load_kernel()  # ensures test_scope is importable as a top-level module
    import test_scope.select as select_mod
    from test_scope.policy import ScopePolicy as RealScopePolicy

    monkeypatch.setattr(select_mod, "ScopePolicy", lambda: RealScopePolicy(core_fanin_threshold=1))

    (fixture_monorepo / "packages/a/src/pa/x.py").write_text("X = 2\n")

    rc = main(["--tier", "merge", "--base", "HEAD", "--worktree", str(fixture_monorepo), "--run"])
    assert rc == 0
    capsys.readouterr()  # discard the first call's shell-line + subprocess output

    main(["--tier", "merge", "--base", "HEAD", "--worktree", str(fixture_monorepo), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert "a" in payload["skipped_escalations"]


def test_run_rearms_escalation_on_a_later_red_run(fixture_monorepo, capsys, monkeypatch):
    """FEAT-563 review (R14/AC9c): a red run on a core-escalation invocation must re-arm it — a
    stale ledger record for that distribution must not survive a red run, even one that predates
    (or otherwise never matched) the current core-file content.

    A distribution whose ledger entry already matches the current content is *skipped* by
    `pending_escalations` — the escalated invocation is then never even added to the plan, so it
    cannot go red "for real" through this path. This test instead seeds a ledger entry that does
    NOT match (so the escalation is still attempted, exactly like a genuinely-stale or corrupted
    record would be) and asserts a subsequent red run clears it rather than leaving a misleading
    record behind."""
    from scripts.sdd.select_tests import _load_kernel

    kernel = _load_kernel()
    import test_scope.select as select_mod
    from test_scope.policy import ScopePolicy as RealScopePolicy

    monkeypatch.setattr(select_mod, "ScopePolicy", lambda: RealScopePolicy(core_fanin_threshold=1))

    (fixture_monorepo / "packages/a/src/pa/x.py").write_text("X = 2\n")
    # Seed a ledger entry with no matching blobs, so pending_escalations does NOT skip "a"/"b".
    kernel.context.record_green_escalation(fixture_monorepo, ["a", "b"], [])
    assert "a" in kernel.context.read_ledger(fixture_monorepo)

    (fixture_monorepo / "packages/a/tests/test_x.py").write_text("def test_x():\n    assert False\n")
    rc = main(["--tier", "merge", "--base", "HEAD", "--worktree", str(fixture_monorepo), "--run"])
    assert rc == 1  # "a"'s escalated suite failed; "b"'s passed

    ledger = kernel.context.read_ledger(fixture_monorepo)
    assert "a" not in ledger  # re-armed: the stale/red entry was dropped, not left in place
    assert "b" in ledger  # "b" was green and got a fresh, correct record
