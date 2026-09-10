"""Deterministic Git fixtures for the tool-optimizations tests (FEAT-543).

Every repository is created with pinned identity, pinned dates and no
signing, so commit shas are stable and the suite never touches the
developer's global Git configuration.
"""

import os
import subprocess
from pathlib import Path

import pytest

#: Environment used for every fixture Git command. Global/system config are
#: neutralized so a developer's settings cannot change fixture behavior.
ENV = {
    **os.environ,
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "LC_ALL": "C",
    "LANG": "C",
}


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a Git command in ``cwd`` with the deterministic fixture environment.

    Args:
        cwd: Working directory for the command.
        *args: Git arguments, without the leading ``git``.
        check: Raise on a non-zero exit code.

    Returns:
        The completed process.
    """
    return subprocess.run(["git", *args], cwd=cwd, env=ENV, capture_output=True, text=True, check=check)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A repository on branch ``dev`` with a single commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "dev")
    git(repo, "config", "commit.gpgsign", "false")
    (repo / "a.py").write_text("print('a')\n")
    git(repo, "add", "a.py")
    git(repo, "commit", "-q", "-m", "init")
    return repo


@pytest.fixture
def bare_remote(git_repo: Path, tmp_path: Path) -> Path:
    """A local bare remote registered as ``origin`` with ``dev`` pushed."""
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    git(git_repo, "remote", "add", "origin", str(remote))
    git(git_repo, "push", "-q", "origin", "dev")
    return remote


@pytest.fixture
def linked_worktree(git_repo: Path, tmp_path: Path) -> Path:
    """A linked worktree of ``git_repo`` (its ``.git`` is a file, not a dir)."""
    worktree = tmp_path / "wt"
    git(git_repo, "worktree", "add", "-q", "-b", "feat", str(worktree))
    return worktree
