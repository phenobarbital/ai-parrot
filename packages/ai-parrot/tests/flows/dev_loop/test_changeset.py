"""Git-measured ``ChangeSet`` (the PR-style +/- file list of a run).

Exercised against a real repository (the same ``origin/dev`` ladder the
``files_changed`` reconciliation tests use) so numstat/name-status
parsing is checked on git's actual output, not on hand-written strings.
"""

from __future__ import annotations

import subprocess

import pytest

from parrot.flows.dev_loop.models import ChangeSet
from parrot.flows.dev_loop.nodes._changeset import (
    _parse_numstat,
    _parse_porcelain,
    _rename_target,
    compute_changeset,
    record_changeset,
    resolve_base_ref,
)
from parrot.flows.dev_loop.session_state import SessionHost


def _git(worktree, *args: str) -> None:
    subprocess.run(["git", *args], cwd=worktree, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    """A worktree on a feature branch cut from a local ``origin/dev``."""
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "dev")
    _git(origin, "config", "user.email", "t@t.t")
    _git(origin, "config", "user.name", "t")
    (origin / "seed.txt").write_text("one\ntwo\nthree\n")
    (origin / "old_name.py").write_text("x = 1\n")
    _git(origin, "add", "-A")
    _git(origin, "commit", "-qm", "seed")

    work = tmp_path / "work"
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True, capture_output=True)
    _git(work, "config", "user.email", "t@t.t")
    _git(work, "config", "user.name", "t")
    _git(work, "checkout", "-q", "-b", "feat-1-x")
    return work


@pytest.mark.asyncio
async def test_numstat_per_file_and_totals(repo):
    (repo / "seed.txt").write_text("one\nTWO\nthree\nfour\n")  # +2 -1
    (repo / "pkg").mkdir()
    (repo / "pkg" / "new.py").write_text("a = 1\nb = 2\n")  # +2, added
    (repo / "blob.bin").write_bytes(b"\x00\x01\x02")  # binary
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "work")

    cs = await compute_changeset(str(repo), "dev", branch="feat-1-x")

    assert isinstance(cs, ChangeSet)
    assert cs.base_ref == "origin/dev"
    assert cs.branch == "feat-1-x"
    assert cs.commits == 1
    by_path = {f.path: f for f in cs.files}
    assert by_path["seed.txt"].additions == 2 and by_path["seed.txt"].deletions == 1
    assert by_path["seed.txt"].status == "M"
    assert by_path["pkg/new.py"].status == "A" and by_path["pkg/new.py"].additions == 2
    assert by_path["blob.bin"].binary is True and by_path["blob.bin"].status == "A"
    assert cs.total_additions == 4 and cs.total_deletions == 1
    assert cs.uncommitted == 0
    assert [f.path for f in cs.files] == sorted(f.path for f in cs.files)


@pytest.mark.asyncio
async def test_rename_and_delete_statuses(repo):
    _git(repo, "mv", "old_name.py", "new_name.py")
    (repo / "seed.txt").unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "reshape")

    cs = await compute_changeset(str(repo), "dev")

    by_path = {f.path: f for f in cs.files}
    assert by_path["new_name.py"].status == "R"
    assert "old_name.py" not in by_path
    assert by_path["seed.txt"].status == "D" and by_path["seed.txt"].deletions == 3


@pytest.mark.asyncio
async def test_uncommitted_and_untracked_work_is_included(repo):
    (repo / "seed.txt").write_text("one\ntwo\nthree\nfour\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "committed")
    (repo / "seed.txt").write_text("one\ntwo\nthree\nfour\nfive\n")  # +1 uncommitted on top
    (repo / "test_new.py").write_text("def test(): pass\n")  # untracked

    cs = await compute_changeset(str(repo), "dev")

    by_path = {f.path: f for f in cs.files}
    assert by_path["seed.txt"].additions == 2  # 1 committed + 1 working tree
    assert by_path["test_new.py"].status == "?"
    assert cs.uncommitted == 2


@pytest.mark.asyncio
async def test_empty_diff_against_true_base_is_not_reattributed(repo):
    """A branch with nothing committed reports nothing — never the base's history."""
    cs = await compute_changeset(str(repo), "dev")
    assert cs is not None
    assert cs.files == [] and cs.commits == 0


@pytest.mark.asyncio
async def test_non_git_directory_yields_none(tmp_path):
    assert await compute_changeset(str(tmp_path), "dev") is None
    assert await resolve_base_ref(str(tmp_path), "dev") is None


@pytest.mark.asyncio
async def test_missing_base_falls_back_to_origin_dev(repo):
    assert await resolve_base_ref(str(repo), "no-such-branch") == "origin/dev"
    assert await resolve_base_ref(str(repo), "") == "origin/dev"


@pytest.mark.asyncio
async def test_record_changeset_publishes_to_shared_and_session_state(repo):
    (repo / "seed.txt").write_text("changed\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "work")
    host = SessionHost("run-1")
    shared = {"session_host": host}

    cs = await record_changeset(shared, str(repo), "dev", branch="feat-1-x")

    assert shared["changeset"] is cs
    assert host.state.changeset == cs
    assert host.state.changeset.files[0].path == "seed.txt"


@pytest.mark.asyncio
async def test_record_changeset_without_git_leaves_shared_untouched(tmp_path):
    shared = {}
    assert await record_changeset(shared, str(tmp_path), "dev") is None
    assert "changeset" not in shared


def test_numstat_parser_handles_binary_and_rename_spellings():
    parsed = _parse_numstat("3\t1\ta.py\n-\t-\timg.png\n0\t0\tsrc/{old => new}/f.py\n1\t0\told => new.txt\n")
    assert parsed["a.py"] == (3, 1, False)
    assert parsed["img.png"] == (0, 0, True)
    assert parsed["src/new/f.py"] == (0, 0, False)
    assert parsed["new.txt"] == (1, 0, False)
    assert _rename_target("plain.py") == "plain.py"


def test_porcelain_parser_statuses():
    parsed = _parse_porcelain("?? new.py\n M edited.py\nD  gone.py\nA  staged.py\nR  a.py -> b.py\n")
    assert parsed == {"new.py": "?", "edited.py": "M", "gone.py": "D", "staged.py": "A", "b.py": "R"}
