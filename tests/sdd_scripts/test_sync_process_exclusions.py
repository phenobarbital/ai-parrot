"""Regression tests for explicit worktree PID exclusions."""

import os
from pathlib import Path

import pytest

from parrot.sdd.scripts import remove_worktree


def _mock_proc_entries(*pids: int) -> list[Path]:
    """Return synthetic ``/proc`` entries for a PID collection."""
    return [Path(f"/proc/{pid}") for pid in pids]


def test_default_keeps_foreign_and_parent_processes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Default callers retain foreign cwd matches and omit only self."""
    worktree = tmp_path / "worktree"
    parent_pid = 101
    foreign_pid = 102
    own_pid = os.getpid()
    cwd_by_pid = {
        parent_pid: worktree,
        foreign_pid: worktree / "child",
        own_pid: worktree / "self",
    }
    monkeypatch.setattr(remove_worktree.Path, "iterdir", lambda _: _mock_proc_entries(parent_pid, foreign_pid, own_pid))
    monkeypatch.setattr(remove_worktree, "_proc_cwd", lambda pid: cwd_by_pid[pid])
    monkeypatch.setattr(remove_worktree, "_proc_cmdline", lambda pid: f"process-{pid}")

    assert remove_worktree.live_processes_in(worktree) == [
        (parent_pid, f"process-{parent_pid}"),
        (foreign_pid, f"process-{foreign_pid}"),
    ]


def test_explicit_exclusions_preserve_other_matches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Excluded ancestors disappear without hiding a sibling worker."""
    worktree = tmp_path / "worktree"
    excluded_pids = (201, 202)
    sibling_pid = 203
    unrelated_pid = 204
    unreadable_pid = 205
    own_pid = os.getpid()
    cwd_by_pid = {
        excluded_pids[0]: worktree,
        excluded_pids[1]: worktree / "nested",
        sibling_pid: worktree / "worker",
        unrelated_pid: tmp_path / "worktree-other",
        own_pid: worktree / "self",
        unreadable_pid: None,
    }
    monkeypatch.setattr(
        remove_worktree.Path,
        "iterdir",
        lambda _: _mock_proc_entries(*excluded_pids, sibling_pid, unrelated_pid, unreadable_pid, own_pid),
    )
    monkeypatch.setattr(remove_worktree, "_proc_cwd", lambda pid: cwd_by_pid[pid])
    monkeypatch.setattr(remove_worktree, "_proc_cmdline", lambda pid: f"process-{pid}")

    assert remove_worktree.live_processes_in(worktree, exclude_pids=excluded_pids) == [
        (sibling_pid, f"process-{sibling_pid}"),
    ]
    assert excluded_pids == (201, 202)
