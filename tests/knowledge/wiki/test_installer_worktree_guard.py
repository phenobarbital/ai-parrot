"""Tests for TASK-3237: worktree structural-hook guard + post-merge install.

FEAT-566 Module 10 — the ``post-commit``/``post-merge`` hooks must no-op
the structural ``wikitoolkit upsert --changed`` inside a linked worktree
(its ``.git`` is a file, never a directory), while the main checkout keeps
running the upsert exactly as before. The installer must resolve both
hooks against the shared/common ``hooks/`` directory (never a per-worktree
one) and manage ``post-merge`` installation idempotently, without
clobbering unrelated hook content.
"""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

from parrot.knowledge.wiki.claude_code import assets
from parrot.knowledge.wiki.claude_code.installer import (
    _git_hook_path,
    _install_git_hook,
    _install_post_merge_hook,
)

#: Marker the stub ``wikitoolkit`` binary writes when actually invoked, so
#: tests can observe whether the guard let the upsert run.
_MARKER_NAME = "wikitoolkit_ran.marker"


def _install_stub_wikitoolkit(root: Path) -> None:
    """Install a fake ``<root>/.venv/bin/wikitoolkit`` that just leaves a marker.

    ``resolve_wikitoolkit_bin`` resolves this path first, so hook content
    generated for ``root`` invokes this stub instead of a real binary.
    """
    bin_dir = root / ".venv" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "wikitoolkit"
    stub.write_text(
        "#!/bin/sh\n"
        f'touch "{root / _MARKER_NAME}"\n'
        "exit 0\n",
        encoding="utf-8",
    )
    mode = stub.stat().st_mode
    stub.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _run_hook(hook_path: Path, cwd: Path) -> None:
    """Execute a generated hook script with ``cwd`` as the repo root."""
    subprocess.run(["sh", str(hook_path)], cwd=str(cwd), check=True, timeout=10)


class TestMainCheckoutHookRunsUpsert:
    """A regular (non-worktree) checkout retains the upsert behavior."""

    def test_post_commit_hook_runs_upsert(self, tmp_path: Path) -> None:
        repo = tmp_path
        (repo / ".git").mkdir()
        _install_stub_wikitoolkit(repo)

        _install_git_hook(repo)
        hook_path = _git_hook_path(repo, "post-commit")
        assert hook_path is not None and hook_path.exists()

        _run_hook(hook_path, cwd=repo)
        assert (repo / _MARKER_NAME).exists()

    def test_post_merge_hook_runs_upsert(self, tmp_path: Path) -> None:
        repo = tmp_path
        (repo / ".git").mkdir()
        _install_stub_wikitoolkit(repo)

        _install_post_merge_hook(repo)
        hook_path = _git_hook_path(repo, "post-merge")
        assert hook_path is not None and hook_path.exists()

        _run_hook(hook_path, cwd=repo)
        assert (repo / _MARKER_NAME).exists()


class _LinkedWorktreeFixture:
    """Builds a `<main>/main .git dir` + `<main>/worktree .git file` pair."""

    def __init__(self, tmp_path: Path) -> None:
        self.main_dir = tmp_path / "main"
        self.main_dir.mkdir()
        self.main_git = self.main_dir / ".git"
        self.main_git.mkdir()

        self.worktree_dir = tmp_path / "linked"
        self.worktree_dir.mkdir()
        worktree_git_dir = self.main_git / "worktrees" / "linked"
        worktree_git_dir.mkdir(parents=True)
        (worktree_git_dir / "commondir").write_text("../..\n", encoding="utf-8")
        (self.worktree_dir / ".git").write_text(
            f"gitdir: {worktree_git_dir}\n", encoding="utf-8"
        )


class TestLinkedWorktreeHookSkipsUpsert:
    """A linked worktree's hook exits before the upsert ever runs."""

    def test_post_commit_hook_skips_upsert_in_linked_worktree(self, tmp_path: Path) -> None:
        fixture = _LinkedWorktreeFixture(tmp_path)
        _install_stub_wikitoolkit(fixture.worktree_dir)

        _install_git_hook(fixture.worktree_dir)
        hook_path = _git_hook_path(fixture.worktree_dir, "post-commit")
        assert hook_path is not None and hook_path.exists()
        # Resolved against the COMMON git dir, not a nonexistent per-worktree one.
        assert hook_path == fixture.main_git / "hooks" / "post-commit"

        _run_hook(hook_path, cwd=fixture.worktree_dir)
        assert not (fixture.worktree_dir / _MARKER_NAME).exists()

    def test_post_merge_hook_skips_upsert_in_linked_worktree(self, tmp_path: Path) -> None:
        fixture = _LinkedWorktreeFixture(tmp_path)
        _install_stub_wikitoolkit(fixture.worktree_dir)

        _install_post_merge_hook(fixture.worktree_dir)
        hook_path = _git_hook_path(fixture.worktree_dir, "post-merge")
        assert hook_path is not None and hook_path.exists()
        assert hook_path == fixture.main_git / "hooks" / "post-merge"

        _run_hook(hook_path, cwd=fixture.worktree_dir)
        assert not (fixture.worktree_dir / _MARKER_NAME).exists()


class TestPostMergeInstallerIdempotency:
    """Installer manages the post-merge hook the same way it manages post-commit."""

    def test_post_merge_hook_created_then_idempotent(self, tmp_path: Path) -> None:
        repo = tmp_path
        (repo / ".git").mkdir()

        first = _install_post_merge_hook(repo)
        assert "created" in first

        hook_path = _git_hook_path(repo, "post-merge")
        assert hook_path is not None
        first_content = hook_path.read_text(encoding="utf-8")
        assert first_content.count(assets.GIT_HOOK_BEGIN) == 1

        second = _install_post_merge_hook(repo)
        assert "already installed" in second
        assert hook_path.read_text(encoding="utf-8") == first_content

    def test_post_merge_hook_chains_into_unrelated_existing_hook(self, tmp_path: Path) -> None:
        repo = tmp_path
        (repo / ".git").mkdir()
        hook_path = repo / ".git" / "hooks" / "post-merge"
        hook_path.parent.mkdir(parents=True)
        hook_path.write_text("#!/bin/sh\necho 'unrelated existing hook'\n", encoding="utf-8")

        action = _install_post_merge_hook(repo)
        assert "chained into existing hook" in action

        content = hook_path.read_text(encoding="utf-8")
        assert "unrelated existing hook" in content
        assert assets.GIT_HOOK_BEGIN in content

    def test_no_git_repo_skips_post_merge_hook(self, tmp_path: Path) -> None:
        action = _install_post_merge_hook(tmp_path)
        assert action == "git post-merge hook — skipped (not a git repository)"
