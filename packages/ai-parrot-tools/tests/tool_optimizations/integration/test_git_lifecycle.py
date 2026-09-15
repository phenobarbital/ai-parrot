"""End-to-end Git lifecycle, main tree and linked worktree (TASK-3091)."""

from pathlib import Path

import pytest
from parrot_tools.tool_optimizations.git import LocalGitToolkit

from .conftest import git


def _index_bytes(repo: Path) -> bytes:
    """Read a worktree's own index bytes.

    In a linked worktree `.git` is a *file* pointing at the real git dir,
    so the main repo's index is not the one that changes.
    """
    dot_git = repo / ".git"
    if dot_git.is_file():
        gitdir = Path(dot_git.read_text().split("gitdir:", 1)[1].strip())
        return (gitdir / "index").read_bytes()
    return (dot_git / "index").read_bytes()


@pytest.fixture
def repo_with_remote(tmp_path):
    """A repo on `dev` with a local bare remote and one commit pushed."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "dev")
    git(repo, "config", "commit.gpgsign", "false")
    (repo / "a.py").write_text("print('a')\n")
    git(repo, "add", "a.py")
    git(repo, "commit", "-q", "-m", "base")

    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "-u", "origin", "dev")
    return repo, remote


async def test_full_lifecycle_in_main_tree(repo_with_remote):
    """fetch -> preflight -> prepare -> (test commits) -> push -> pull."""
    repo, remote = repo_with_remote
    toolkit = LocalGitToolkit(repo_root=repo)

    fetched = await toolkit.git_fetch(remote="origin", branch="dev", recent=1)
    assert fetched.status == "ok" and fetched.data["fresh"] is True

    preflight = await toolkit.git_preflight()
    assert preflight.status == "ok"
    assert preflight.data["branch"] == "dev"

    (repo / "b.py").write_text("b = 1\n")
    prepared = await toolkit.git_prepare_files(["b.py"])
    assert prepared.status == "ok", prepared.error
    assert prepared.data["staged"] == ["b.py"]

    # The toolkit never commits — the harness does.
    git(repo, "commit", "-q", "-m", "add b")
    head = git(repo, "rev-parse", "HEAD").stdout.strip()

    pushed = await toolkit.git_push(branch="dev")
    assert pushed.status == "ok", pushed.error
    assert git(remote, "rev-parse", "refs/heads/dev").stdout.strip() == head

    pulled = await toolkit.git_pull()
    assert pulled.status == "ok"
    assert pulled.data["updated"] is False  # already up to date


async def test_lifecycle_in_linked_worktree(repo_with_remote, tmp_path):
    """A linked worktree stages into its own index, never the main one."""
    repo, _remote = repo_with_remote
    worktree = tmp_path / "wt"
    git(repo, "worktree", "add", "-q", "-b", "feat", str(worktree))

    main_index_before = _index_bytes(repo)
    toolkit = LocalGitToolkit(repo_root=worktree)

    layout = await toolkit._discover()
    assert layout.is_linked_worktree is True

    (worktree / "w.py").write_text("w = 1\n")
    prepared = await toolkit.git_prepare_files(["w.py"])
    assert prepared.status == "ok", prepared.error

    staged = [item for item in git(worktree, "diff", "--cached", "--name-only", "-z").stdout.split("\0") if item]
    assert staged == ["w.py"]
    assert _index_bytes(repo) == main_index_before, "the main index must be untouched"


async def test_injected_whitespace_failure_preserves_everything(repo_with_remote):
    """A failing check leaves refs, files and index bytes byte-identical."""
    repo, remote = repo_with_remote
    toolkit = LocalGitToolkit(repo_root=repo)

    (repo / "bad.py").write_text("x = 1 \n")  # trailing whitespace
    index_before = _index_bytes(repo)
    head_before = git(repo, "rev-parse", "HEAD").stdout.strip()
    remote_before = git(remote, "rev-parse", "refs/heads/dev").stdout.strip()

    result = await toolkit.git_prepare_files(["bad.py"])
    assert result.status == "error"
    assert result.error.code == "whitespace_errors"

    assert _index_bytes(repo) == index_before
    assert git(repo, "rev-parse", "HEAD").stdout.strip() == head_before
    assert git(remote, "rev-parse", "refs/heads/dev").stdout.strip() == remote_before
    assert (repo / "bad.py").read_text() == "x = 1 \n"


async def test_injected_foreign_index_lock_preserves_index(repo_with_remote):
    """A lock owned by another git process blocks publication, harmlessly."""
    repo, _remote = repo_with_remote
    toolkit = LocalGitToolkit(repo_root=repo)

    (repo / "c.py").write_text("c = 1\n")
    lock = repo / ".git" / "index.lock"
    lock.write_bytes(b"")
    index_before = _index_bytes(repo)

    result = await toolkit.git_prepare_files(["c.py"])
    assert result.error.code == "index_locked"
    assert lock.exists(), "a foreign lock must never be deleted"
    assert _index_bytes(repo) == index_before
    lock.unlink()


async def test_diverged_remote_blocks_pull_and_push(repo_with_remote, tmp_path):
    """Divergence is refused by both directions, with nothing changed."""
    repo, remote = repo_with_remote

    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(remote), str(other))
    git(other, "checkout", "-q", "-B", "dev", "origin/dev")
    (other / "remote_only.py").write_text("r = 1\n")
    git(other, "add", "remote_only.py")
    git(other, "commit", "-q", "-m", "remote")
    git(other, "push", "-q", "origin", "dev")

    (repo / "local_only.py").write_text("l = 1\n")
    git(repo, "add", "local_only.py")
    git(repo, "commit", "-q", "-m", "local")

    toolkit = LocalGitToolkit(repo_root=repo)
    head_before = git(repo, "rev-parse", "HEAD").stdout.strip()

    pulled = await toolkit.git_pull()
    assert pulled.error.code == "diverged"
    assert git(repo, "rev-parse", "HEAD").stdout.strip() == head_before

    pushed = await toolkit.git_push(branch="dev")
    assert pushed.error.code == "push_rejected"
    # The remote still holds only its own commit.
    assert git(remote, "rev-parse", "refs/heads/dev").stdout.strip() != head_before
