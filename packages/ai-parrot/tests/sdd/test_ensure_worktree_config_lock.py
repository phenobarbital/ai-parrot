"""Sandbox ``config.lock`` stub: policy no longer creates it, ``ensure`` heals an existing one."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from parrot.sdd.config import SddConfig
from parrot.sdd.scripts import ensure_worktree as ew
from parrot.sdd.scripts.brief_meta import brief_worktree_plan


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A real clone whose ``origin`` carries a ``dev`` branch."""
    origin = tmp_path / "origin.git"
    _git("init", "--bare", "-b", "dev", str(origin), cwd=tmp_path)
    clone = tmp_path / "clone"
    _git("clone", str(origin), str(clone), cwd=tmp_path)
    _git("config", "user.email", "t@example.com", cwd=clone)
    _git("config", "user.name", "t", cwd=clone)
    _git("checkout", "-b", "dev", cwd=clone)
    (clone / "f.txt").write_text("x\n")
    _git("add", "f.txt", cwd=clone)
    _git("commit", "-m", "init", cwd=clone)
    _git("push", "-u", "origin", "dev", cwd=clone)
    return clone


def _plan():
    return brief_worktree_plan(slug="demo", key="abc123", base_branch="dev", config=SddConfig())


def test_denied_paths_exclude_config_lock_but_keep_config(tmp_path: Path) -> None:
    """Listing the nonexistent lock only leaves a host stub; ``config`` itself stays denied."""
    from parrot.sdd.scripts import native_claude_sandbox as native

    main = tmp_path / "main"
    git_dir = main / ".git"
    admin = git_dir / "worktrees" / "feat"
    admin.mkdir(parents=True)
    (admin / "commondir").write_text("../..\n")
    root = main / ".parrot" / "worktrees" / "feat"
    root.mkdir(parents=True)
    (root / ".git").write_text(f"gitdir: {admin}\n")
    denied = native._denied_write_paths(root, git_dir)
    assert str((git_dir / "config").resolve()) in denied
    assert not any(Path(entry).name == "config.lock" for entry in denied)


def test_ensure_removes_readonly_empty_stub(repo: Path) -> None:
    lock = repo / ".git" / "config.lock"
    lock.touch()
    lock.chmod(0o444)
    path, created = ew.ensure(_plan(), repo_root=repo)
    assert created and path.is_dir()
    assert not lock.exists()


def test_ensure_leaves_real_lock_untouched(repo: Path) -> None:
    lock = repo / ".git" / "config.lock"
    lock.write_text("[core]\n")
    lock.chmod(0o644)
    with pytest.raises(ew.EnsureWorktreeError):
        ew.ensure(_plan(), repo_root=repo)
    assert lock.read_text() == "[core]\n"


def test_ensure_leaves_writable_empty_lock_untouched(repo: Path) -> None:
    lock = repo / ".git" / "config.lock"
    lock.touch()
    lock.chmod(0o644)
    assert ew._clear_sandbox_config_lock(repo) is False
    assert lock.exists()


def _bwrap_usable() -> bool:
    if shutil.which("bwrap") is None:
        return False
    probe = subprocess.run(["bwrap", "--bind", "/", "/", "true"], capture_output=True)
    return probe.returncode == 0


@pytest.mark.skipif(not _bwrap_usable(), reason="bwrap unavailable or user namespaces denied")
def test_readonly_config_bind_blocks_git_config_without_lock_deny(repo: Path) -> None:
    """Only ``.git/config`` ro-bound: config writes still fail and no lock is left behind."""
    config = repo / ".git" / "config"
    before = config.read_bytes()
    res = subprocess.run(
        ["bwrap", "--bind", "/", "/", "--dev", "/dev", "--ro-bind", str(config), str(config),
         "git", "-C", str(repo), "config", "core.hooksPath", "x"],
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert config.read_bytes() == before
    assert not (repo / ".git" / "config.lock").exists()
