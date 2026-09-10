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
def test_exposes_exactly_the_expected_tools(git_repo):
    """The toolkit exposes exactly its six tools; each is a real AbstractTool."""
    tools = LocalGitToolkit(repo_root=git_repo).get_tools()
    assert {tool.name for tool in tools} == {
        "git_recent",
        "git_fetch",
        "git_preflight",
        "git_prepare_files",
        "git_pull",
        "git_push",
    }
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


# =========================================================================== #
# TASK-3081 — mutations: prepare / pull / push
# =========================================================================== #
def _clone_on_dev(bare_remote: Path, tmp_path: Path) -> Path:
    """Clone the bare remote and check out `dev`.

    The bare remote's HEAD points at `master` (git's default for
    `init --bare`), so a plain clone lands on an unborn branch and would
    push `master` instead of `dev`.
    """
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(bare_remote), str(other))
    git(other, "checkout", "-q", "-B", "dev", "origin/dev")
    return other


def _index_bytes(repo: Path) -> bytes:
    """Read the raw index bytes, or b'' when the index does not exist yet."""
    index = repo / ".git" / "index"
    return index.read_bytes() if index.exists() else b""


def test_mutating_tools_require_confirmation(git_repo):
    """The three mutations are marked destructive; the reads are not."""
    tools = {tool.name: tool for tool in LocalGitToolkit(repo_root=git_repo).get_tools()}
    assert set(tools) == {"git_recent", "git_fetch", "git_preflight", "git_prepare_files", "git_pull", "git_push"}
    for name in ("git_prepare_files", "git_pull", "git_push"):
        assert (tools[name].routing_meta or {}).get("requires_confirmation") is True
    for name in ("git_recent", "git_fetch", "git_preflight"):
        assert not (tools[name].routing_meta or {}).get("requires_confirmation")


async def test_mcp_tools_list_marks_confirm_required(git_repo):
    """tools/list advertises `confirm` as required only for the mutations."""
    from parrot.mcp.local_server import StdioMCPServer
    from parrot.mcp.server_base import LocalServerConfig

    server = StdioMCPServer(LocalServerConfig(name="t"))
    server.register_tools(LocalGitToolkit(repo_root=git_repo).get_tools())
    listing = await server._handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    schemas = {tool["name"]: tool["inputSchema"] for tool in listing["result"]["tools"]}

    for name in ("git_prepare_files", "git_pull", "git_push"):
        assert "confirm" in schemas[name]["required"]
        assert schemas[name]["properties"]["confirm"]["type"] == "boolean"
    assert "confirm" not in schemas["git_recent"].get("required", [])
    assert "confirm" not in schemas["git_recent"]["properties"]


async def test_mcp_call_rejected_without_confirm(git_repo):
    """A mutation invoked over MCP without confirm=true is refused."""
    from parrot.mcp.local_server import StdioMCPServer
    from parrot.mcp.server_base import LocalServerConfig

    server = StdioMCPServer(LocalServerConfig(name="t"))
    server.register_tools(LocalGitToolkit(repo_root=git_repo).get_tools())
    before = _index_bytes(git_repo)
    response = await server._handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "git_prepare_files", "arguments": {"paths": ["a.py"]}},
        }
    )
    assert response["result"]["isError"] is True
    assert _index_bytes(git_repo) == before


# --------------------------------------------------------------------------- #
# git_prepare_files — refusals preserve the index byte-for-byte
# --------------------------------------------------------------------------- #
async def test_prepare_refuses_unrelated_staging_and_preserves_index(git_repo):
    """Unrelated staged paths cause refusal; nothing is ever unstaged."""
    (git_repo / "b.py").write_text("b = 1\n")
    git(git_repo, "add", "b.py")
    (git_repo / "a.py").write_text("print('A')\n")
    before = _index_bytes(git_repo)

    res = await LocalGitToolkit(repo_root=git_repo).git_prepare_files(["a.py"])
    assert res.status == "error"
    assert res.error.code == "unrelated_staged"
    assert res.error.details["unrelated"] == ["b.py"]
    assert _index_bytes(git_repo) == before


async def test_prepare_refuses_partially_staged(git_repo):
    """Whole-file staging must not silently replace a partially staged hunk."""
    (git_repo / "a.py").write_text("print('one')\n")
    git(git_repo, "add", "a.py")
    (git_repo / "a.py").write_text("print('two')\n")
    before = _index_bytes(git_repo)

    res = await LocalGitToolkit(repo_root=git_repo).git_prepare_files(["a.py"])
    assert res.status == "error"
    assert res.error.code == "partially_staged"
    assert _index_bytes(git_repo) == before


async def test_prepare_whitespace_failure_keeps_original_staging(git_repo):
    """A whitespace failure discards the private index; the real one is intact."""
    (git_repo / "a.py").write_text("print('A') \n")
    before = _index_bytes(git_repo)

    res = await LocalGitToolkit(repo_root=git_repo).git_prepare_files(["a.py"])
    assert res.error.code == "whitespace_errors"
    assert "a.py" in res.error.details["lines"]
    assert _index_bytes(git_repo) == before


async def test_prepare_stages_exact_names_including_deletion_and_unicode(git_repo):
    """Spaces, non-ASCII names and tracked deletions all round-trip via -z."""
    (git_repo / "año nuevo.py").write_text("x = 1\n")
    git(git_repo, "add", "año nuevo.py")
    git(git_repo, "commit", "-q", "-m", "u")
    (git_repo / "a.py").unlink()
    (git_repo / "año nuevo.py").write_text("x = 2\n")

    res = await LocalGitToolkit(repo_root=git_repo).git_prepare_files(["a.py", "año nuevo.py"])
    assert res.status == "ok"
    assert sorted(res.data["staged"]) == ["a.py", "año nuevo.py"]
    assert res.data["deleted"] == ["a.py"]
    assert res.data["whitespace_ok"] is True
    assert res.data["index_published"] is True

    staged = [item for item in git(git_repo, "diff", "--cached", "--name-only", "-z").stdout.split("\0") if item]
    assert sorted(staged) == ["a.py", "año nuevo.py"]


async def test_prepare_accepts_already_fully_staged_selection(git_repo):
    """A selected path that is already fully staged is not a conflict."""
    (git_repo / "a.py").write_text("print('A')\n")
    git(git_repo, "add", "a.py")
    res = await LocalGitToolkit(repo_root=git_repo).git_prepare_files(["a.py"])
    assert res.status == "ok", (res.error.code, res.error.details)
    assert res.data["staged"] == ["a.py"]


async def test_prepare_respects_foreign_index_lock(git_repo):
    """A lock owned by another git process is reported, never deleted."""
    (git_repo / "a.py").write_text("print('A')\n")
    lock = git_repo / ".git" / "index.lock"
    lock.write_bytes(b"")
    before = _index_bytes(git_repo)

    res = await LocalGitToolkit(repo_root=git_repo).git_prepare_files(["a.py"])
    assert res.error.code == "index_locked", (res.error.code, res.error.details)
    assert lock.exists()
    assert _index_bytes(git_repo) == before


async def test_prepare_refuses_unmerged_index(git_repo, tmp_path):
    """An unmerged index must be resolved by a human first."""
    git(git_repo, "checkout", "-q", "-b", "other")
    (git_repo / "a.py").write_text("other side\n")
    git(git_repo, "commit", "-q", "-am", "other")
    git(git_repo, "checkout", "-q", "dev")
    (git_repo / "a.py").write_text("dev side\n")
    git(git_repo, "commit", "-q", "-am", "dev")
    git(git_repo, "merge", "other", check=False)  # conflicts

    res = await LocalGitToolkit(repo_root=git_repo).git_prepare_files(["a.py"])
    assert res.status == "error"
    assert res.error.code == "unmerged_index"


@pytest.mark.parametrize(
    "bad_path,expected",
    [
        ("pkg", "directory_rejected"),
        ("*.py", "glob_rejected"),
        (":(top)a.py", "pathspec_magic"),
        # '..' is caught by the shape check, before path resolution — an
        # earlier and stricter rejection than containment would give.
        ("../outside.py", "invalid_path"),
        (".env", "secret_file"),
        ("link.py", "symlink_rejected"),
        ("nope.py", "path_not_found"),
        ("a.py/", "invalid_path"),
        ("/etc/passwd", "invalid_path"),
    ],
)
async def test_prepare_rejects_unsafe_paths_before_any_write(git_repo, bad_path, expected):
    """Every unsafe path shape is refused with the index left untouched."""
    (git_repo / "pkg").mkdir()
    (git_repo / ".env").write_text("SECRET=1\n")
    (git_repo / "link.py").symlink_to(git_repo / "a.py")
    before = _index_bytes(git_repo)

    res = await LocalGitToolkit(repo_root=git_repo).git_prepare_files([bad_path])
    assert res.status == "error"
    assert res.error.code == expected
    assert _index_bytes(git_repo) == before


async def test_prepare_rejects_duplicate_paths(git_repo):
    """The same file twice is a caller error, not a silent de-duplication."""
    (git_repo / "a.py").write_text("print('A')\n")
    res = await LocalGitToolkit(repo_root=git_repo).git_prepare_files(["a.py", "./a.py"])
    assert res.status == "error"
    assert res.error.code in {"invalid_path", "duplicate_path"}


async def test_prepare_publishes_to_linked_worktree_index(linked_worktree, git_repo):
    """A linked worktree stages into its own index, not the main one."""
    main_index_before = _index_bytes(git_repo)
    (linked_worktree / "w.py").write_text("w = 1\n")

    res = await LocalGitToolkit(repo_root=linked_worktree).git_prepare_files(["w.py"])
    assert res.status == "ok"
    assert res.data["staged"] == ["w.py"]
    assert _index_bytes(git_repo) == main_index_before

    layout = await LocalGitToolkit(repo_root=linked_worktree)._discover()
    assert ".git/worktrees/" in layout.index_path.as_posix()
    staged = [item for item in git(linked_worktree, "diff", "--cached", "--name-only", "-z").stdout.split("\0") if item]
    assert staged == ["w.py"]


async def test_prepare_leaves_no_temporary_index_files(git_repo):
    """The private index copy is always removed, on success and on failure."""
    (git_repo / "a.py").write_text("print('A')\n")
    toolkit = LocalGitToolkit(repo_root=git_repo)
    await toolkit.git_prepare_files(["a.py"])
    (git_repo / "a.py").write_text("print('B') \n")
    await toolkit.git_prepare_files(["a.py"])
    assert list((git_repo / ".git").glob("parrot-index-*")) == []


# --------------------------------------------------------------------------- #
# git_pull
# --------------------------------------------------------------------------- #
async def test_pull_ff_only_then_up_to_date(git_repo, bare_remote, tmp_path):
    """A real fast-forward updates the branch; a second pull is a no-op."""
    other = _clone_on_dev(bare_remote, tmp_path)
    (other / "c.py").write_text("c\n")
    git(other, "add", "c.py")
    git(other, "commit", "-q", "-m", "c")
    git(other, "push", "-q")
    git(git_repo, "branch", "--set-upstream-to", "origin/dev", "dev")

    toolkit = LocalGitToolkit(repo_root=git_repo)
    first = await toolkit.git_pull()
    assert first.status == "ok"
    assert first.data["updated"] is True
    assert first.data["before"] != first.data["after"]
    assert (git_repo / "c.py").exists()

    second = await toolkit.git_pull()
    assert second.status == "ok"
    assert second.data["updated"] is False


async def test_pull_diverged(git_repo, bare_remote, tmp_path):
    """Divergence is refused; no merge commit is ever created."""
    other = _clone_on_dev(bare_remote, tmp_path)
    (other / "c.py").write_text("c\n")
    git(other, "add", "c.py")
    git(other, "commit", "-q", "-m", "c")
    git(other, "push", "-q")
    (git_repo / "d.py").write_text("d\n")
    git(git_repo, "add", "d.py")
    git(git_repo, "commit", "-q", "-m", "d")
    git(git_repo, "branch", "--set-upstream-to", "origin/dev", "dev")

    res = await LocalGitToolkit(repo_root=git_repo).git_pull()
    assert res.status == "error"
    assert res.error.code == "diverged"
    assert res.error.details["ahead"] == 1
    assert res.error.details["behind"] == 1


async def test_pull_preserves_conflicting_untracked_file(git_repo, bare_remote, tmp_path):
    """Git refuses to clobber an untracked file, and its content survives."""
    other = _clone_on_dev(bare_remote, tmp_path)
    (other / "c.py").write_text("from remote\n")
    git(other, "add", "c.py")
    git(other, "commit", "-q", "-m", "c")
    git(other, "push", "-q")
    (git_repo / "c.py").write_text("MINE - untracked\n")
    git(git_repo, "branch", "--set-upstream-to", "origin/dev", "dev")

    res = await LocalGitToolkit(repo_root=git_repo).git_pull()
    assert res.status == "error"
    assert res.error.code == "untracked_conflict"
    assert (git_repo / "c.py").read_text() == "MINE - untracked\n"


async def test_pull_refuses_dirty_and_staged_and_detached(git_repo, bare_remote):
    """Unsafe working-tree states are refused before any network access."""
    git(git_repo, "branch", "--set-upstream-to", "origin/dev", "dev")
    toolkit = LocalGitToolkit(repo_root=git_repo)

    (git_repo / "a.py").write_text("dirty\n")
    assert (await toolkit.git_pull()).error.code == "dirty_worktree"

    git(git_repo, "add", "a.py")
    assert (await toolkit.git_pull()).error.code == "staged_changes"

    git(git_repo, "restore", "-q", "--staged", "--worktree", "a.py")
    head = git(git_repo, "rev-parse", "HEAD").stdout.strip()
    git(git_repo, "checkout", "-q", "--detach", head)
    assert (await LocalGitToolkit(repo_root=git_repo).git_pull()).error.code == "detached_head"


async def test_pull_missing_upstream_and_branch_mismatch(git_repo, bare_remote):
    """Branch resolution refuses ambiguity rather than guessing."""
    toolkit = LocalGitToolkit(repo_root=git_repo)
    assert (await toolkit.git_pull()).error.code == "missing_upstream"
    assert (await toolkit.git_pull(branch="main")).error.code == "branch_mismatch"


# --------------------------------------------------------------------------- #
# git_push
# --------------------------------------------------------------------------- #
async def test_push_succeeds_to_bare_remote(git_repo, bare_remote):
    """A fast-forward push reports the branch and the remote's new commit."""
    (git_repo / "d.py").write_text("d\n")
    git(git_repo, "add", "d.py")
    git(git_repo, "commit", "-q", "-m", "d")
    local = git(git_repo, "rev-parse", "HEAD").stdout.strip()

    res = await LocalGitToolkit(repo_root=git_repo).git_push(branch="dev")
    assert res.status == "ok"
    assert res.data["branch"] == "dev"
    assert res.data["local_commit"] == local
    assert res.data["remote_commit_after"] == local
    remote_head = git(bare_remote, "rev-parse", "refs/heads/dev").stdout.strip()
    assert remote_head == local


async def test_push_rejected_without_force(git_repo, bare_remote, tmp_path):
    """A remote that moved ahead rejects the push; it is never forced."""
    other = _clone_on_dev(bare_remote, tmp_path)
    (other / "c.py").write_text("c\n")
    git(other, "add", "c.py")
    git(other, "commit", "-q", "-m", "c")
    git(other, "push", "-q")
    (git_repo / "d.py").write_text("d\n")
    git(git_repo, "add", "d.py")
    git(git_repo, "commit", "-q", "-m", "d")

    res = await LocalGitToolkit(repo_root=git_repo).git_push(branch="dev")
    assert res.status == "error"
    assert res.error.code == "push_rejected"
    assert "rejected" in res.error.details["summary"].lower()


async def test_push_timeout_is_uncertain_then_resolved(git_repo, bare_remote, tmp_path, monkeypatch):
    """A timed-out push is uncertain, and is resolved by one read-only probe."""
    real_git = shutil.which("git")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    fake_git.write_text(textwrap.dedent(f"""\
            #!/bin/sh
            for arg in "$@"; do
              if [ "$arg" = "push" ]; then sleep 30; fi
            done
            exec {real_git} "$@"
            """))
    fake_git.chmod(fake_git.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ['PATH']}")

    # The remote already has exactly our HEAD, so ls-remote resolves it to ok.
    toolkit = LocalGitToolkit(repo_root=git_repo, network_timeout_seconds=0.4)
    res = await toolkit.git_push(branch="dev")
    assert res.status == "ok"
    assert res.data["resolved_after_timeout"] is True

    # Now make the local branch differ, so the probe cannot resolve it.
    (git_repo / "d.py").write_text("d\n")
    git(git_repo, "add", "d.py")
    git(git_repo, "commit", "-q", "-m", "d")
    unresolved = await LocalGitToolkit(repo_root=git_repo, network_timeout_seconds=0.4).git_push(branch="dev")
    assert unresolved.status == "uncertain"
    assert unresolved.error.code == "push_timeout"
    assert unresolved.data["resolved_after_timeout"] is False


async def test_push_refuses_detached_head(git_repo, bare_remote):
    """A detached HEAD has no branch to publish."""
    head = git(git_repo, "rev-parse", "HEAD").stdout.strip()
    git(git_repo, "checkout", "-q", "--detach", head)
    res = await LocalGitToolkit(repo_root=git_repo).git_push()
    assert res.error.code == "detached_head"


def test_push_porcelain_parsers():
    """Porcelain flags and commit ranges are parsed, not guessed."""
    from parrot_tools.tool_optimizations.git import _parse_push_porcelain, _parse_push_range

    ok = "To /tmp/r.git\n \trefs/heads/dev:refs/heads/dev\taaaaaaa..bbbbbbb\nDone\n"
    assert _parse_push_porcelain(ok) == (" ", "refs/heads/dev:refs/heads/dev", "aaaaaaa..bbbbbbb")
    assert _parse_push_range("aaaaaaa..bbbbbbb") == ("aaaaaaa", "bbbbbbb")
    assert _parse_push_range("[new branch]") == (None, None)

    rejected = "To /tmp/r.git\n!\trefs/heads/dev:refs/heads/dev\t[rejected] (fetch first)\nDone\n"
    assert _parse_push_porcelain(rejected)[0] == "!"
    assert _parse_push_porcelain("")[0] == ""


# --------------------------------------------------------------------------- #
# Forbidden verbs
# --------------------------------------------------------------------------- #
def test_no_forbidden_git_verbs_in_source():
    """The module can never reset, stash, force-push or push all refs."""
    import inspect

    import parrot_tools.tool_optimizations.git as module

    src = inspect.getsource(module)
    for bad in ('"reset"', '"stash"', '"--force"', '"--force-with-lease"', '"--all"', '"--mirror"', '"rebase"'):
        assert bad not in src, f"forbidden git argv literal present: {bad}"


async def test_prepare_stages_same_size_edit_made_in_the_same_clock_tick(git_repo):
    """A same-size edit right after `git add` must still be staged.

    Regression test. Git decides an index entry is "racily clean" by
    comparing the entry's mtime against the *index file's* mtime, and
    re-hashes the file when it is. Copying the index with a fresh mtime
    silently converts those entries into trusted-clean ones, so a same-size
    edit made within the same (coarse, ~ms) filesystem clock tick as the
    last `git add` was not staged. Plain `git diff` never misses it, so
    neither may this toolkit.
    """
    toolkit = LocalGitToolkit(repo_root=git_repo)
    for index in range(25):
        # Same byte length as the committed content, written immediately.
        (git_repo / "a.py").write_text(f"print('{index:02d}')\n")
        res = await toolkit.git_prepare_files(["a.py"])
        assert res.status == "ok", (index, res.error.code, res.error.details)
        assert res.data["staged"] == ["a.py"]
        git(git_repo, "commit", "-q", "-m", f"c{index}")
