"""Tests for shared root resolution and ledger path functionality."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from parrot.knowledge.wiki.project import (
    find_shared_root,
    is_linked_worktree,
    resolve_git_common_dir,
)


class TestGitCommonDirResolution:
    def test_resolve_git_common_dir_regular_repo(self, tmp_path: Path) -> None:
        """Test resolving common dir for a regular repository."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        result = resolve_git_common_dir(git_dir)
        assert result == git_dir

    def test_resolve_git_common_dir_linked_worktree_with_relative_commondir(self, tmp_path: Path) -> None:
        """Test resolving common dir for a linked worktree with relative commondir."""
        # Create worktree directory structure
        worktree_dir = tmp_path / "feature"
        worktree_dir.mkdir()
        worktree_git = worktree_dir / ".git"
        worktree_git.write_text("gitdir: ../main/.git/worktrees/feature\n", encoding="utf-8")

        # Create main repository structure
        main_dir = tmp_path / "main"
        main_dir.mkdir()
        main_git = main_dir / ".git"
        main_git.mkdir()

        # Create worktree git directory with commondir file
        worktree_git_dir = main_git / "worktrees" / "feature"
        worktree_git_dir.mkdir(parents=True)
        commondir = worktree_git_dir / "commondir"
        commondir.write_text("../..\n", encoding="utf-8")

        result = resolve_git_common_dir(worktree_git)
        assert result == main_git

    def test_resolve_git_common_dir_linked_worktree_with_absolute_commondir(self, tmp_path: Path) -> None:
        """A worktree's `commondir` file may hold an absolute path to the main .git dir."""
        main_git_dir = tmp_path / "main" / ".git"
        main_git_dir.mkdir(parents=True)

        worktree_git_dir = main_git_dir / "worktrees" / "feature"
        worktree_git_dir.mkdir(parents=True)
        (worktree_git_dir / "commondir").write_text(str(main_git_dir) + "\n", encoding="utf-8")

        linked_git_file = tmp_path / "worktree" / ".git"
        linked_git_file.parent.mkdir(parents=True)
        linked_git_file.write_text(f"gitdir: {worktree_git_dir}\n", encoding="utf-8")

        assert resolve_git_common_dir(linked_git_file) == main_git_dir

    def test_resolve_git_common_dir_nonexistent(self, tmp_path: Path) -> None:
        """Test resolving common dir for a nonexistent path."""
        git_dir = tmp_path / "nonexistent"
        with pytest.raises(FileNotFoundError):
            resolve_git_common_dir(git_dir)


class TestIsLinkedWorktree:
    def test_is_linked_worktree_with_file(self, tmp_path: Path) -> None:
        """Test detecting a linked worktree (git dir is a file)."""
        git_file = tmp_path / ".git"
        git_file.write_text("gitdir: ../main/.git/worktrees/feature\n", encoding="utf-8")

        assert is_linked_worktree(git_file) is True

    def test_is_linked_worktree_with_directory(self, tmp_path: Path) -> None:
        """Test detecting a regular repository (git dir is a directory)."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        assert is_linked_worktree(git_dir) is False

    def test_is_linked_worktree_nonexistent(self, tmp_path: Path) -> None:
        """Test with a nonexistent path."""
        git_path = tmp_path / "nonexistent"
        assert is_linked_worktree(git_path) is False


class TestFindSharedRoot:
    def test_find_shared_root_regular_repo(self, tmp_path: Path) -> None:
        """Test finding shared root in a regular repository."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        git_dir = repo_root / ".git"
        git_dir.mkdir()

        # Change to the repo directory to test
        original_cwd = os.getcwd()
        try:
            os.chdir(str(repo_root))
            result = find_shared_root()
            assert result == repo_root
        finally:
            os.chdir(original_cwd)

    def test_find_shared_root_no_git(self, tmp_path: Path) -> None:
        """Test finding shared root when no git repo exists."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        original_cwd = os.getcwd()
        try:
            os.chdir(str(repo_root))
            result = find_shared_root()
            assert result is None
        finally:
            os.chdir(original_cwd)

    def test_find_shared_root_with_start_param(self, tmp_path: Path) -> None:
        """Test finding shared root with explicit start parameter."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        git_dir = repo_root / ".git"
        git_dir.mkdir()

        result = find_shared_root(repo_root)
        assert result == repo_root

    def test_find_shared_root_tolerance_to_failures(self, tmp_path: Path) -> None:
        """Test that find_shared_root tolerates failures gracefully."""
        # This test ensures the function doesn't crash on unexpected inputs
        # The function should return None rather than raising exceptions
        result = find_shared_root(Path("/nonexistent/path/that/should/not/exist"))
        assert result is None


def test_ledger_path_method_exists() -> None:
    """Test that WikiProjectConfig has the ledger_path method."""
    from parrot.knowledge.wiki.project import PARROT_DIR, WikiProjectConfig

    config = WikiProjectConfig()
    # Create a mock root path
    root = Path("/test/root")

    # Check that the method exists and works
    assert hasattr(config, "ledger_path")
    ledger_path = config.ledger_path(root)
    expected_path = root / PARROT_DIR / "ledger"
    assert ledger_path == expected_path
    assert str(ledger_path).endswith(".parrot/ledger")
