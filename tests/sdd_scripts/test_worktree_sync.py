"""Real temporary Git integration tests for worktree sync."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from parrot.sdd.scripts import worktree_sync


def _run(path: Path, *args: str) -> str:
    """Run Git in a disposable repository and return stdout."""
    return subprocess.run(["git", "-C", str(path), *args], text=True, capture_output=True, check=True).stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create a primary clone, its bare origin, and a linked feature worktree."""
    origin = tmp_path / "origin.git"
    primary = tmp_path / "primary"
    feature = tmp_path / "feature"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "clone", str(origin), str(primary)], check=True, capture_output=True, text=True)
    _run(primary, "config", "user.email", "test@example.invalid")
    _run(primary, "config", "user.name", "Sync Test")
    (primary / "shared.txt").write_text("base\n", encoding="utf-8")
    _run(primary, "add", "shared.txt")
    _run(primary, "commit", "-m", "initial")
    _run(primary, "branch", "-M", "dev")
    _run(primary, "push", "-u", "origin", "dev")
    _run(primary, "worktree", "add", "-b", "feat-FEAT-999-sync", str(feature), "dev")
    return origin, primary, feature


def test_host_merge_from_outside(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A new base commit is integrated into a registered feature worktree."""
    _origin, primary, feature = _repository(tmp_path)
    (primary / "base.txt").write_text("from base\n", encoding="utf-8")
    _run(primary, "add", "base.txt")
    _run(primary, "commit", "-m", "base update")
    _run(primary, "push")

    monkeypatch.delenv(worktree_sync.BACKEND_ENV, raising=False)
    result = worktree_sync.sync(feature, "dev")

    assert result.exit_code == worktree_sync.EXIT_OK
    assert result.status == "synced"
    assert (feature / "base.txt").read_text(encoding="utf-8") == "from base\n"
    assert _run(feature, "status", "--porcelain") == ""


def test_conflict_aborts_and_restores_head(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Conflicting merge restores HEAD, index and tree and reports paths."""
    _origin, primary, feature = _repository(tmp_path)
    monkeypatch.delenv(worktree_sync.BACKEND_ENV, raising=False)
    (feature / "shared.txt").write_text("feature\n", encoding="utf-8")
    _run(feature, "add", "shared.txt")
    _run(feature, "commit", "-m", "feature change")
    before = _run(feature, "rev-parse", "HEAD")
    (primary / "shared.txt").write_text("base change\n", encoding="utf-8")
    _run(primary, "add", "shared.txt")
    _run(primary, "commit", "-m", "base change")
    _run(primary, "push")

    result = worktree_sync.sync(feature, "dev")

    assert result.exit_code == worktree_sync.EXIT_CONFLICT
    assert result.status == "conflict"
    assert result.before == result.after == before
    assert result.conflicts == ["shared.txt"]
    assert _run(feature, "status", "--porcelain") == ""
    assert (feature / "shared.txt").read_text(encoding="utf-8") == "feature\n"


def test_stale_base_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Advisory covers ahead, current, and sandbox cases without changing the tree."""
    _origin, primary, feature = _repository(tmp_path)
    (primary / "base.txt").write_text("from base\n", encoding="utf-8")
    _run(primary, "add", "base.txt")
    _run(primary, "commit", "-m", "base update")
    _run(primary, "push")
    before = _run(feature, "rev-parse", "HEAD")

    monkeypatch.delenv(worktree_sync.BACKEND_ENV, raising=False)
    summary = worktree_sync.stale_base_summary(feature, "dev")
    assert "1 commit(s) ahead" in summary
    assert _run(feature, "rev-parse", "HEAD") == before
    assert _run(feature, "status", "--porcelain") == ""

    monkeypatch.setenv(worktree_sync.BACKEND_ENV, "native")
    assert worktree_sync.stale_base_summary(feature, "dev").startswith("stale-base check skipped:")
