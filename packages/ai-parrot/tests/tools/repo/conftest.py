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


@pytest.fixture
def temp_worktree(temp_repo: Path, tmp_path: Path) -> Path:
    """A real `git worktree add` off temp_repo — drives plane resolution."""
    wt = tmp_path / "wt"
    subprocess.run(
        ["git", "worktree", "add", "-q", "-b", "wt-branch", str(wt), "HEAD"],
        cwd=temp_repo,
        check=True,
    )
    return wt


class _StubStore:
    """Answers search_fts with fixed rows; neighbors with fixed edges.

    Row shape mirrors ``BaseWikiStore.search_fts``'s real SQL projection
    (``store.py``: ``concept_id, node_id, title, category, summary,
    source_id, token_count, score``) — note the key is ``summary``, which
    is what ``WikiCombinedSearch._store_row_to_wiki`` reads into
    ``WikiSearchResult.snippet``.
    """

    def __init__(self, rows=None, neighbors=None, raises=False):
        self._rows = (
            rows
            if rows is not None
            else [
                {
                    "concept_id": "file:pkg/sub/mod.py",
                    "title": "pkg/sub/mod.py",
                    "summary": "def alpha(): ...",
                    "score": 0.9,
                    "token_count": 120,
                },
            ]
        )
        self._neighbors = neighbors or [
            {"concept_id": "dir:pkg", "title": "pkg", "rel": "contains"},
        ]
        self._raises = raises
        self.fts_calls = 0

    async def search_fts(self, query, category=None, limit=10):
        self.fts_calls += 1
        if self._raises:
            raise RuntimeError("plane is broken")
        return list(self._rows)

    async def search_vector(self, embedding, limit=10):
        return []

    async def neighbors(self, concept_id, rel=None, direction="both"):
        if self._raises:
            raise RuntimeError("plane is broken")
        return list(self._neighbors)


@pytest.fixture
def stub_wiki_store():
    return _StubStore()


@pytest.fixture
def broken_wiki_store():
    return _StubStore(raises=True)
