"""Reusable fake venv and linked-worktree fixtures for launcher tests."""

from __future__ import annotations

from pathlib import Path

import pytest


def make_venv(path: Path, *scripts: str) -> Path:
    """Create a fake venv with script stubs, matching the existing helper exactly."""
    (path / "bin").mkdir(parents=True)
    (path / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    for name in scripts:
        (path / "bin" / name).write_text("#!/bin/sh\n", encoding="utf-8")
    return path


@pytest.fixture
def linked_worktree_repo(tmp_path: Path) -> tuple[Path, Path]:
    """Create a primary checkout and a linked-worktree gitdir with commondir."""
    main = tmp_path / "main"
    admin = main / ".git" / "worktrees" / "wt"
    admin.mkdir(parents=True)
    (admin / "commondir").write_text("../..\n", encoding="utf-8")
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {admin}\n", encoding="utf-8")
    return main, wt
