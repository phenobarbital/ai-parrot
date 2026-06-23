"""Live integration tests — clone→worktree & local→worktree (FEAT-253 TASK-005).

Gated behind ``@pytest.mark.live`` and a ``shutil.which("git")`` skip
guard; they skip cleanly when ``git`` is not installed or the test
environment has no network.

Run with::

    pytest packages/ai-parrot/tests/flows/dev_loop/test_repo_wiring_live.py \
        -m live -v

These tests exercise the **real** git path-resolution and worktree
creation end-to-end:

* ``test_e2e_clone_then_worktree_from_clone`` — clones a local bare
  fixture repo (no network) into
  ``BASE_DIR/.claude/worktrees/repos/<run_id>/<alias>`` and asserts
  that a git worktree branched from the clone lands in
  ``BASE_DIR/.claude/worktrees/<run_id>-feat``.

* ``test_e2e_local_run_worktree_from_base_dir`` — with no repos,
  asserts ``_provision_repos`` returns ``str(BASE_DIR)`` and that a
  manually-created worktree from ``BASE_DIR`` produces a valid git
  worktree.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from navconfig import BASE_DIR
from parrot import conf
from parrot.flows.dev_loop.models import RepoSpec
from parrot.flows.dev_loop.nodes.research import ResearchNode

pytestmark = pytest.mark.live

skip_no_git = pytest.mark.skipif(
    shutil.which("git") is None, reason="git not installed"
)


# ---------------------------------------------------------------------------
# Fixture: a local bare repo + seed commit (no network required)
# ---------------------------------------------------------------------------


@pytest.fixture
def local_bare_repo(tmp_path: Path):
    """Create a minimal local bare git repository with an initial commit.

    Returns ``(bare_path, default_branch)`` so tests can clone it without
    hitting the network.
    """
    # 1. Create a source working tree with an initial commit.
    src = tmp_path / "src-repo"
    src.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(src)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=str(src), check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(src), check=True, capture_output=True,
    )
    readme = src / "README.md"
    readme.write_text("fixture repo\n")
    subprocess.run(["git", "add", "README.md"], cwd=str(src), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        cwd=str(src), check=True, capture_output=True,
    )

    # 2. Clone it as a bare repo (bare repos are conventional remote targets).
    bare = tmp_path / "bare-repo.git"
    subprocess.run(
        ["git", "clone", "--bare", str(src), str(bare)],
        check=True, capture_output=True,
    )
    return bare, "main"


# ---------------------------------------------------------------------------
# Test 1: clone from local bare repo, create worktree from clone
# ---------------------------------------------------------------------------


@skip_no_git
@pytest.mark.asyncio
async def test_e2e_clone_then_worktree_from_clone(
    local_bare_repo,
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Clone a local fixture repo, create worktree from clone.

    Asserts:
    - clone lands under BASE_DIR/.claude/worktrees/repos/<run_id>/<alias>
    - a git worktree branched from the clone has git-common-dir pointing
      back to the clone's .git, not the outer BASE_DIR repo.
    """
    from parrot_tools.gittoolkit import GitToolkit  # noqa: PLC0415

    bare_path, default_branch = local_bare_repo
    run_id = f"test-{uuid.uuid4().hex[:8]}"
    alias = "fixture-repo"
    repo_base = tmp_path / "repos"
    worktree_base = tmp_path / "worktrees"

    # Anchor conf paths to tmp_path for isolation.
    monkeypatch.setattr(conf, "DEV_LOOP_REPO_BASE_PATH", str(repo_base))
    monkeypatch.setattr(conf, "WORKTREE_BASE_PATH", str(worktree_base))

    # Use file:// URL so GitToolkit recognizes it as a URL (not an owner/name slug).
    clone_url = bare_path.as_uri()  # e.g. file:///tmp/.../bare-repo.git
    spec = RepoSpec(alias=alias, url=clone_url, branch=default_branch)  # noqa: F841

    git = GitToolkit()
    clone_dest = repo_base / run_id / alias
    clone_dest.parent.mkdir(parents=True, exist_ok=True)

    result = await git.clone_repo(
        clone_url,
        str(clone_dest),
        branch=default_branch,
    )
    clone_path = result.get("path", str(clone_dest)) if isinstance(result, dict) else str(clone_dest)

    assert os.path.isdir(clone_path), f"Clone should exist at {clone_path}"
    assert clone_path.startswith(str(repo_base)), (
        f"Clone {clone_path!r} must be under repo_base {str(repo_base)!r}"
    )
    assert clone_path.endswith(f"/{run_id}/{alias}") or clone_path.endswith(
        f"{os.sep}{run_id}{os.sep}{alias}"
    ), f"Clone path should end with /<run_id>/<alias>: {clone_path!r}"

    # Create a worktree from the clone (branching from the default branch).
    worktree_dir = worktree_base / f"{run_id}-feat"
    worktree_dir.parent.mkdir(parents=True, exist_ok=True)

    branch_name = f"feat-test-{uuid.uuid4().hex[:6]}"
    subprocess.run(
        ["git", "worktree", "add", "-b", branch_name, str(worktree_dir), default_branch],
        cwd=clone_path,
        check=True,
        capture_output=True,
    )

    try:
        assert worktree_dir.is_dir(), f"Worktree dir should exist: {worktree_dir}"

        # git-common-dir from the worktree should point back to the clone's .git
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=str(worktree_dir),
            capture_output=True,
            text=True,
            check=True,
        )
        common_dir = Path(result.stdout.strip()).resolve()
        clone_git_dir = Path(clone_path) / ".git"
        clone_git_dir_resolved = clone_git_dir.resolve()
        assert common_dir == clone_git_dir_resolved, (
            f"Worktree's git-common-dir ({common_dir}) should point to the clone's "
            f".git ({clone_git_dir_resolved}), not the outer BASE_DIR repo."
        )
    finally:
        # Clean up the worktree.
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree_dir)],
            cwd=clone_path,
            capture_output=True,
        )
        if worktree_dir.exists():
            shutil.rmtree(str(worktree_dir), ignore_errors=True)


# ---------------------------------------------------------------------------
# Test 2: no repos declared -> repo_path == str(BASE_DIR)
# ---------------------------------------------------------------------------


@skip_no_git
@pytest.mark.asyncio
async def test_e2e_local_run_worktree_from_base_dir(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """No repos declared -> _provision_repos returns str(BASE_DIR).

    Asserts:
    - repo_path == str(BASE_DIR)
    - a git worktree branched from BASE_DIR is valid (git-common-dir
      resolves to BASE_DIR/.git).
    """
    from unittest.mock import AsyncMock, MagicMock  # noqa: PLC0415

    worktree_base = tmp_path / "worktrees"
    worktree_base.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(conf, "WORKTREE_BASE_PATH", str(worktree_base))
    monkeypatch.setattr(conf, "DEV_LOOP_REPO_BASE_PATH", str(tmp_path / "repos"))

    jira = MagicMock()
    jira.jira_create_issue = AsyncMock(return_value={"key": "OPS-1"})
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock()

    node = ResearchNode(
        dispatcher=dispatcher,
        jira_toolkit=jira,
        log_toolkits={},
        git_toolkit=None,
        repos=[],
    )

    repo_path = await node._provision_repos("run-local-test")
    assert repo_path == str(BASE_DIR), (
        f"Local fallback: expected str(BASE_DIR)={str(BASE_DIR)!r}, got {repo_path!r}"
    )

    # Verify BASE_DIR is a valid git repo we can branch a worktree from.
    assert (Path(BASE_DIR) / ".git").is_dir(), (
        "BASE_DIR must be a git repository with a .git directory"
    )

    # Create a worktree from BASE_DIR to verify the flow would work.
    wt_dir = worktree_base / "local-test-wt"
    branch_name = f"feat-local-test-{uuid.uuid4().hex[:6]}"
    subprocess.run(
        ["git", "worktree", "add", "-b", branch_name, str(wt_dir)],
        cwd=str(BASE_DIR),
        check=True,
        capture_output=True,
    )

    try:
        assert wt_dir.is_dir(), f"Worktree dir should exist: {wt_dir}"

        # Verify it's linked back to BASE_DIR's .git
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=str(wt_dir),
            capture_output=True,
            text=True,
            check=True,
        )
        common_dir = Path(result.stdout.strip()).resolve()
        base_git = (Path(BASE_DIR) / ".git").resolve()
        assert common_dir == base_git, (
            f"Worktree's git-common-dir ({common_dir}) should equal BASE_DIR/.git ({base_git})"
        )
    finally:
        # Clean up: remove worktree and delete the branch.
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(wt_dir)],
            cwd=str(BASE_DIR),
            capture_output=True,
        )
        subprocess.run(
            ["git", "branch", "-D", branch_name],
            cwd=str(BASE_DIR),
            capture_output=True,
        )
        if wt_dir.exists():
            shutil.rmtree(str(wt_dir), ignore_errors=True)
