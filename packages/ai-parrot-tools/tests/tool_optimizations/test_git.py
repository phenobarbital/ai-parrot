"""Unit tests for LocalGitToolkit discovery/read/fetch (TASK-3080, FEAT-543)."""

import os
import shutil
import stat
import textwrap
from pathlib import Path

import pytest
from parrot.tools.abstract import AbstractTool

from parrot_tools.tool_optimizations.git import GIT_ENV, LocalGitToolkit, RepoLayout, _parse_status_v2
from parrot_tools.tool_optimizations.models import OperationResult

from .conftest import git


# --------------------------------------------------------------------------- #
# Tool surface
# --------------------------------------------------------------------------- #
def test_exposes_exactly_the_read_and_fetch_tools(git_repo):
    """Only this task's three tools exist; each is a real AbstractTool."""
    tools = LocalGitToolkit(repo_root=git_repo).get_tools()
    assert {tool.name for tool in tools} == {"git_recent", "git_fetch", "git_preflight"}
    assert all(isinstance(tool, AbstractTool) for tool in tools)


def test_git_env_is_noninteractive():
    """The forced environment cannot prompt, page or interpret pathspec magic."""
    assert GIT_ENV["GIT_TERMINAL_PROMPT"] == "0"
    assert GIT_ENV["GIT_LITERAL_PATHSPECS"] == "1"
    assert GIT_ENV["GIT_OPTIONAL_LOCKS"] == "0"
    # User config must still apply (remotes, credential helpers).
    assert "GIT_CONFIG_NOSYSTEM" not in GIT_ENV


# --------------------------------------------------------------------------- #
# git_recent
# --------------------------------------------------------------------------- #
async def test_recent_limit_and_option_shaped_ref(git_repo):
    """History is bounded, and an option-shaped ref never reaches a subprocess."""
    toolkit = LocalGitToolkit(repo_root=git_repo)
    res = await toolkit.git_recent(limit=1)
    assert res.status == "ok"
    assert len(res.data["commits"]) == 1
    assert res.data["commits"][0]["subject"] == "init"
    assert len(res.data["commit"]) == 40

    bad = await toolkit.git_recent(ref="--upload-pack=/bin/sh")
    assert bad.status == "error"
    assert bad.error.code == "invalid_ref"
    assert bad.steps == []


async def test_recent_rejects_out_of_range_limit_on_direct_call(git_repo):
    """A direct Python call is validated too, not only the MCP seam."""
    toolkit = LocalGitToolkit(repo_root=git_repo)
    for limit in (0, 51):
        res = await toolkit.git_recent(limit=limit)
        assert res.status == "error"
        assert res.error.code == "invalid_arguments"
        assert res.steps == []


async def test_recent_rejects_out_of_range_limit_via_pre_execute(git_repo):
    """_pre_execute rejects the same value at the raw-argument boundary."""
    toolkit = LocalGitToolkit(repo_root=git_repo)
    with pytest.raises(ValueError, match="invalid arguments"):
        await toolkit._pre_execute("git_recent", limit=51)


async def test_recent_unknown_ref(git_repo):
    """A syntactically valid but nonexistent ref is reported, not crashed on."""
    res = await LocalGitToolkit(repo_root=git_repo).git_recent(ref="no-such-branch")
    assert res.status == "error"
    assert res.error.code == "unknown_ref"


# --------------------------------------------------------------------------- #
# git_fetch
# --------------------------------------------------------------------------- #
async def test_fetch_reports_fetched_and_fresh(git_repo, bare_remote):
    """A normal fetch reports the fetched commit and a matching tracking ref."""
    res = await LocalGitToolkit(repo_root=git_repo).git_fetch(remote="origin", branch="dev", recent=1)
    assert res.status == "ok"
    assert res.data["fresh"] is True
    assert res.data["fetched_commit"] == res.data["tracking_commit"]
    assert res.data["tracking_ref"] == "refs/remotes/origin/dev"
    assert len(res.data["commits"]) == 1


async def test_fetch_unknown_remote_never_fetches(git_repo, bare_remote):
    """An unconfigured remote is refused before any network step."""
    res = await LocalGitToolkit(repo_root=git_repo).git_fetch(remote="nope")
    assert res.status == "error"
    assert res.error.code == "unknown_remote"
    assert "fetch" not in [step.name for step in res.steps]


@pytest.mark.parametrize("branch", ["origin/dev:dev", "HEAD~1", "dev@{upstream}", "-x", "dev..main", "dev.lock"])
async def test_fetch_rejects_non_branch_values(git_repo, bare_remote, branch):
    """Refspecs, revision expressions and option-shaped values are rejected."""
    res = await LocalGitToolkit(repo_root=git_repo).git_fetch(branch=branch)
    assert res.status == "error"
    assert res.error.code == "invalid_branch"


async def test_fetch_failure_stops_history(git_repo, bare_remote):
    """A failed fetch must not fall through to a history lookup."""
    shutil.rmtree(bare_remote)
    res = await LocalGitToolkit(repo_root=git_repo).git_fetch()
    assert res.status == "error"
    assert res.error.code == "fetch_failed"
    # Only the fetch step is reported: no history lookup was attempted.
    assert [step.name for step in res.steps] == ["fetch"]


async def test_fetch_rejects_non_fast_forward_tracking_update(git_repo, bare_remote, tmp_path):
    """Without a '+' refspec a non-fast-forward tracking update is a rejection."""
    # Rewrite the remote's dev to an unrelated (non-descendant) history.
    other = tmp_path / "other"
    other.mkdir()
    git(other, "init", "-q", "-b", "dev")
    git(other, "config", "commit.gpgsign", "false")
    (other / "z.py").write_text("z\n")
    git(other, "add", "z.py")
    git(other, "commit", "-q", "-m", "unrelated")
    git(other, "push", "-q", "--force", str(bare_remote), "dev")

    # Populate a stale remote-tracking ref first, so the next fetch must
    # move it backwards/sideways.
    git(git_repo, "update-ref", "refs/remotes/origin/dev", "HEAD")

    res = await LocalGitToolkit(repo_root=git_repo).git_fetch()
    assert res.status == "error"
    assert res.error.code == "fetch_rejected"
    assert [step.name for step in res.steps] == ["fetch"]


# --------------------------------------------------------------------------- #
# git_preflight
# --------------------------------------------------------------------------- #
async def test_preflight_runs_every_check(git_repo):
    """Every check reports a result even when an earlier one fails."""
    (git_repo / "a.py").write_text("print('a') \n")  # trailing whitespace
    (git_repo / "b.py").write_text("x = 1\n")
    git(git_repo, "add", "b.py")

    res = await LocalGitToolkit(repo_root=git_repo).git_preflight()
    assert set(res.data["checks"]) == {"status", "diff_check", "cached_check", "staged_names"}
    assert res.data["checks"]["diff_check"]["ok"] is False
    assert res.data["checks"]["status"]["ok"] is True
    assert res.data["staged"] == ["b.py"]
    assert res.status == "error"
    assert res.error.code == "preflight_failed"
    assert res.error.details["failed"] == ["diff_check"]


async def test_preflight_clean_tree(git_repo):
    """A clean tree passes every check and reports its branch."""
    res = await LocalGitToolkit(repo_root=git_repo).git_preflight()
    assert res.status == "ok"
    assert res.data["branch"] == "dev"
    assert res.data["detached"] is False
    assert res.data["unborn"] is False
    assert res.data["counts"]["staged"] == 0
    assert res.data["staged"] == []


async def test_preflight_reports_untracked_and_unstaged(git_repo):
    """Categories are split by the porcelain-v2 XY columns, not guessed."""
    (git_repo / "a.py").write_text("print('changed')\n")
    (git_repo / "new.txt").write_text("hello\n")
    git(git_repo, "add", "a.py")
    (git_repo / "a.py").write_text("print('changed again')\n")

    res = await LocalGitToolkit(repo_root=git_repo).git_preflight()
    # a.py is both staged and unstaged (partially staged).
    assert "a.py" in res.data["paths"]["staged"]
    assert "a.py" in res.data["paths"]["unstaged"]
    assert "new.txt" in res.data["paths"]["untracked"]


async def test_preflight_detached_head(git_repo):
    """A detached HEAD is reported explicitly rather than as a branch name."""
    head = git(git_repo, "rev-parse", "HEAD").stdout.strip()
    git(git_repo, "checkout", "-q", "--detach", head)
    res = await LocalGitToolkit(repo_root=git_repo).git_preflight()
    assert res.data["detached"] is True
    assert res.data["branch"] is None


def test_parse_status_v2_handles_rename_entries():
    """A '2 ' rename entry consumes two NUL records and is attributed once."""
    raw = b"\x00".join(
        [
            b"# branch.oid abc123",
            b"# branch.head dev",
            b"# branch.ab +2 -1",
            b"2 R. N... 100644 100644 100644 aaa bbb R100 new_name.py",
            b"old_name.py",
            b"? untracked.txt",
            b"",
        ]
    )
    summary = _parse_status_v2(raw)
    assert summary["branch"] == "dev"
    assert summary["ahead"] == 2 and summary["behind"] == 1
    assert summary["paths"]["staged"] == ["new_name.py"]
    assert summary["paths"]["unstaged"] == []
    assert summary["paths"]["untracked"] == ["untracked.txt"]


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
async def test_linked_worktree_discovery(linked_worktree):
    """A linked worktree resolves its own git dir and index (.git is a file)."""
    assert (linked_worktree / ".git").is_file()
    layout = await LocalGitToolkit(repo_root=linked_worktree)._discover()
    assert isinstance(layout, RepoLayout)
    assert layout.is_linked_worktree is True
    assert ".git/worktrees/" in layout.git_dir.as_posix()
    assert layout.index_path.exists()
    assert layout.common_dir != layout.git_dir
    assert layout.lock_path.parent == layout.git_dir


async def test_plain_repo_discovery(git_repo):
    """A normal checkout resolves a relative --git-common-dir correctly."""
    layout = await LocalGitToolkit(repo_root=git_repo)._discover()
    assert isinstance(layout, RepoLayout)
    assert layout.is_linked_worktree is False
    assert layout.git_dir == layout.common_dir == git_repo / ".git"
    assert layout.toplevel == git_repo.resolve()


async def test_bare_repository_refused(tmp_path):
    """Worktree operations require a non-bare repository."""
    bare = tmp_path / "bare.git"
    git(tmp_path, "init", "-q", "--bare", str(bare))
    result = await LocalGitToolkit(repo_root=bare)._discover()
    assert isinstance(result, OperationResult)
    assert result.error.code == "bare_repository"


async def test_root_mismatch_refused(git_repo):
    """repo_root must be the work-tree toplevel, not a subdirectory."""
    sub = git_repo / "pkg"
    sub.mkdir()
    result = await LocalGitToolkit(repo_root=sub)._discover()
    assert isinstance(result, OperationResult)
    assert result.error.code == "root_mismatch"


async def test_not_a_repository(tmp_path):
    """A plain directory is reported, not treated as an empty repository."""
    result = await LocalGitToolkit(repo_root=tmp_path)._discover()
    assert isinstance(result, OperationResult)
    assert result.error.code == "not_a_repository"


async def test_discovery_is_cached(git_repo):
    """The layout is resolved once per instance."""
    toolkit = LocalGitToolkit(repo_root=git_repo)
    first = await toolkit._discover()
    assert await toolkit._discover() is first


# --------------------------------------------------------------------------- #
# Runner: bounded output, timeout, cancellation
# --------------------------------------------------------------------------- #
async def test_runner_bounds_large_output_without_deadlock(git_repo):
    """A multi-megabyte stdout is capped but fully drained (no pipe deadlock)."""
    big = git_repo / "big.txt"
    big.write_text("x" * 80 + "\n" * 1)
    payload = ("y" * 79 + "\n") * 70_000  # ~5.5 MiB
    big.write_text(payload)
    git(git_repo, "add", "big.txt")
    git(git_repo, "commit", "-q", "-m", "big")

    toolkit = LocalGitToolkit(repo_root=git_repo)
    step, raw = await toolkit._run_git(["show", "--end-of-options", "HEAD:big.txt"], max_capture=1_048_576)
    assert step.exit_code == 0
    assert step.timed_out is False
    assert step.truncated is True
    assert len(raw) == 1_048_576  # capped, but the child still ran to completion


async def test_runner_times_out_and_kills_child(git_repo, tmp_path, monkeypatch):
    """A hung git is killed and reported as timed out, with no orphan."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    fake_git.write_text(textwrap.dedent("""\
        #!/bin/sh
        sleep 30
        """))
    fake_git.chmod(fake_git.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ['PATH']}")

    toolkit = LocalGitToolkit(repo_root=git_repo, command_timeout_seconds=0.3)
    step, raw = await toolkit._run_git(["status"])
    assert step.timed_out is True
    assert step.exit_code is None
    assert raw == b""


async def test_runner_reports_failure_exit_code(git_repo):
    """A failing command keeps its exit code; truncation cannot mask it."""
    step, _ = await LocalGitToolkit(repo_root=git_repo)._run_git(["rev-parse", "--verify", "--quiet", "nope"])
    assert step.exit_code != 0
    assert step.timed_out is False
