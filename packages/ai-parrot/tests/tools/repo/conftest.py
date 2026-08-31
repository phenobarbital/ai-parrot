"""Shared fixtures for the ReadOnlyRepoToolkit test suite (FEAT-484)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def temp_repo(tmp_path: Path) -> Path:
    """git-init'd repo: nested dirs, an ignored build/ dir, a symlink
    escaping the root, an oversized file, secret files, and two commits."""
    root = tmp_path / "repo"
    (root / "pkg" / "sub").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("")
    (root / "pkg" / "sub" / "mod.py").write_text("def alpha():\n    return 1\n")
    (root / ".gitignore").write_text("build/\n")
    (root / "build").mkdir()
    (root / "build" / "artifact.py").write_text("def alpha():\n    return 2\n")
    # Secret files (§8 Q1)
    (root / ".env").write_text("SECRET_KEY=hunter2\n")
    (root / ".env.example").write_text("SECRET_KEY=\n")
    (root / "server.pem").write_text("-----BEGIN PRIVATE KEY-----\n")
    (root / "config").mkdir()
    (root / "config" / ".env").write_text("NESTED=secret\n")
    # Oversized file for the byte-bound test (TASK-2638)
    (root / "big.txt").write_text("x" * 200_000)
    # Symlink escaping the root
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("do not read me")
    (root / "escape").symlink_to(outside)

    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "first"], cwd=root, check=True)
    (root / "pkg" / "sub" / "mod.py").write_text("def alpha():\n    return 42\n")
    subprocess.run(["git", "commit", "-aqm", "second"], cwd=root, check=True)
    return root
