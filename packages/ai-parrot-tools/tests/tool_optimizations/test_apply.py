"""Tests for writer_apply: gating, rollback, recovery and idempotency (TASK-3086)."""

import os

import pytest

from parrot_tools.tool_optimizations.writer import TargetedWriterToolkit

from .conftest import git
from .fixtures import GOOD_PATCH, make_repo_with_target, make_valid_task
from .test_writer import FakeClient


async def _generated(tmp_path, *, responses=None):
    """Build a git repo, generate an artifact, and return the handles."""
    repo = make_repo_with_target(tmp_path)
    git(repo, "init", "-q", "-b", "dev")
    git(repo, "config", "commit.gpgsign", "false")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "base")
    task = make_valid_task(repo)

    toolkit = TargetedWriterToolkit(repo_root=repo, llm_client=FakeClient(responses or [GOOD_PATCH]))
    generated = await toolkit.writer_generate(task.relative_to(repo).as_posix())
    assert generated.status == "ok", generated.error
    return repo, toolkit, generated.data["artifact_id"], generated.data["patch_sha256"]


# --------------------------------------------------------------------------- #
# Gating
# --------------------------------------------------------------------------- #
async def test_review_hash_gate(tmp_path):
    """Applying requires the hash of the patch the caller actually read."""
    repo, toolkit, artifact_id, _sha = await _generated(tmp_path)
    result = await toolkit.writer_apply(artifact_id, "0" * 64)
    assert result.status == "error"
    assert result.error.code == "review_hash_mismatch"
    assert not (repo / "pkg" / "greeter.py").exists()


async def test_tampered_artifact_refused(tmp_path):
    """An edited stored patch is detected before any precondition runs."""
    repo, toolkit, artifact_id, sha = await _generated(tmp_path)
    patch_file = repo / "artifacts" / "tool-optimizations" / artifact_id / "patch.diff"
    patch_file.write_text(patch_file.read_text() + "+rogue\n")

    result = await toolkit.writer_apply(artifact_id, sha)
    assert result.error.code == "artifact_tampered"
    assert not (repo / "pkg" / "greeter.py").exists()


async def test_unknown_artifact(tmp_path):
    """A missing artifact is reported, not treated as an empty patch."""
    _repo, toolkit, _artifact_id, sha = await _generated(tmp_path)
    result = await toolkit.writer_apply("f" * 32, sha)
    assert result.error.code == "artifact_not_found"


# --------------------------------------------------------------------------- #
# Happy path and idempotency
# --------------------------------------------------------------------------- #
async def test_apply_then_idempotent(tmp_path):
    """A clean apply writes both files, stages nothing and creates no commit."""
    repo, toolkit, artifact_id, sha = await _generated(tmp_path)
    head_before = git(repo, "rev-parse", "HEAD").stdout

    applied = await toolkit.writer_apply(artifact_id, sha)
    assert applied.status == "ok", applied.error
    assert applied.data["already_applied"] is False
    assert sorted(applied.data["applied"]) == ["pkg/__init__.py", "pkg/greeter.py"]

    assert (repo / "pkg" / "greeter.py").read_text() == (
        'def greet(name: str) -> str:\n    """Return a greeting."""\n    return f"hello {name}"\n'
    )
    assert "from .greeter import greet" in (repo / "pkg" / "__init__.py").read_text()

    # Applying never stages, commits or pushes.
    assert git(repo, "diff", "--cached", "--name-only").stdout == ""
    assert git(repo, "rev-parse", "HEAD").stdout == head_before
    assert toolkit._store.read_journal(artifact_id).state == "applied"

    mtimes = {path: (repo / path).stat().st_mtime_ns for path in ("pkg/__init__.py", "pkg/greeter.py")}
    again = await toolkit.writer_apply(artifact_id, sha)
    assert again.status == "ok"
    assert again.data["already_applied"] is True
    assert {path: (repo / path).stat().st_mtime_ns for path in mtimes} == mtimes


async def test_created_file_permissions_and_modify_mode_preserved(tmp_path):
    """A modified file keeps its permissions; a new file is created 0o644."""
    repo, toolkit, artifact_id, sha = await _generated(tmp_path)
    os.chmod(repo / "pkg" / "__init__.py", 0o640)

    assert (await toolkit.writer_apply(artifact_id, sha)).status == "ok"
    assert (repo / "pkg" / "__init__.py").stat().st_mode & 0o777 == 0o640
    assert (repo / "pkg" / "greeter.py").stat().st_mode & 0o777 == 0o644


# --------------------------------------------------------------------------- #
# Preconditions
# --------------------------------------------------------------------------- #
async def test_staged_target_refused_before_changed_target(tmp_path):
    """Staging is checked first, so the report names the real blocker."""
    repo, toolkit, artifact_id, sha = await _generated(tmp_path)
    (repo / "pkg" / "__init__.py").write_text("changed\n")
    git(repo, "add", "pkg/__init__.py")

    result = await toolkit.writer_apply(artifact_id, sha)
    assert result.error.code == "staged_target"
    assert result.error.details["staged"] == ["pkg/__init__.py"]
    assert not (repo / "pkg" / "greeter.py").exists()


async def test_target_changed_refused(tmp_path):
    """A target edited after generation invalidates the patch."""
    repo, toolkit, artifact_id, sha = await _generated(tmp_path)
    (repo / "pkg" / "__init__.py").write_text("changed by a human\n")

    result = await toolkit.writer_apply(artifact_id, sha)
    assert result.error.code == "target_changed"
    assert result.error.details["path"] == "pkg/__init__.py"
    assert (repo / "pkg" / "__init__.py").read_text() == "changed by a human\n"
    assert not (repo / "pkg" / "greeter.py").exists()


async def test_create_collision_refused(tmp_path):
    """A create target that now exists is never overwritten."""
    repo, toolkit, artifact_id, sha = await _generated(tmp_path)
    (repo / "pkg" / "greeter.py").write_text("someone else got there first\n")

    result = await toolkit.writer_apply(artifact_id, sha)
    assert result.error.code == "create_collision"
    assert (repo / "pkg" / "greeter.py").read_text() == "someone else got there first\n"


async def test_unrelated_file_does_not_block_apply(tmp_path):
    """Only declared targets and references gate an apply.

    Reference staleness itself is exercised in `test_contracts.py`: in this
    fixture the only reference *is* a target, so a change to it is caught
    earlier and more precisely as `target_changed`.
    """
    repo, toolkit, artifact_id, sha = await _generated(tmp_path)
    (repo / "pkg" / "unrelated.py").write_text("x = 1\n")

    result = await toolkit.writer_apply(artifact_id, sha)
    assert result.status == "ok"
    assert (repo / "pkg" / "unrelated.py").read_text() == "x = 1\n"


# --------------------------------------------------------------------------- #
# Failure, rollback and recovery
# --------------------------------------------------------------------------- #
async def test_crash_rolls_back_first_file(tmp_path, monkeypatch):
    """A failure on the second file restores the first one exactly."""
    repo, toolkit, artifact_id, sha = await _generated(tmp_path)
    before = (repo / "pkg" / "__init__.py").read_bytes()

    real_replace = os.replace

    # Fault-inject by DESTINATION, not by call count: the journal is also
    # published with os.replace, so a counter would trip on the journal
    # write and never exercise the second target file at all.
    def flaky(src, dst):
        if os.fspath(dst).endswith(os.path.join("pkg", "__init__.py")):
            raise OSError(28, "No space left on device")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    result = await toolkit.writer_apply(artifact_id, sha)
    monkeypatch.undo()

    assert result.status == "error"
    assert result.error.details["errno"] == 28
    # The first target (a create) was written, then rolled back by removal.
    assert not (repo / "pkg" / "greeter.py").exists()
    # The failed target is byte-identical to before.
    assert (repo / "pkg" / "__init__.py").read_bytes() == before

    journal = toolkit._store.read_journal(artifact_id)
    assert journal.state == "rolled_back"
    states = {entry.path: entry.state for entry in journal.entries}
    assert states["pkg/greeter.py"] == "restored"
    assert states["pkg/__init__.py"] == "pending"
    # No adjacent temporary files are left behind.
    assert not list((repo / "pkg").glob(".*parrot-tmp*"))


async def test_concurrent_edit_requires_recovery(tmp_path, monkeypatch):
    """A file a concurrent editor touched is never overwritten by rollback."""
    repo, toolkit, artifact_id, sha = await _generated(tmp_path)

    real_replace = os.replace

    def sabotage(src, dst):
        """Let greeter.py be written, then have a 'concurrent editor' rewrite
        it; fail on the next target so a rollback is attempted."""
        if os.fspath(dst).endswith(os.path.join("pkg", "__init__.py")):
            raise OSError(5, "I/O error")
        result = real_replace(src, dst)
        if os.fspath(dst).endswith(os.path.join("pkg", "greeter.py")):
            with open(dst, "w", encoding="utf-8") as handle:
                handle.write("CONCURRENT EDIT\n")
        return result

    monkeypatch.setattr(os, "replace", sabotage)
    result = await toolkit.writer_apply(artifact_id, sha)
    monkeypatch.undo()

    assert result.status == "error"
    assert result.error.code == "recovery_required"
    assert "pkg/greeter.py" in result.error.details["unrecoverable"]
    # The concurrent editor's content survives untouched — rollback must
    # never overwrite work it did not write itself.
    assert (repo / "pkg" / "greeter.py").read_text() == "CONCURRENT EDIT\n"

    journal = toolkit._store.read_journal(artifact_id)
    assert journal.state == "recovery_required"

    # A retry refuses until a human resolves it.
    retry = await toolkit.writer_apply(artifact_id, sha)
    assert retry.error.code == "recovery_pending"
    assert (repo / "pkg" / "greeter.py").read_text() == "CONCURRENT EDIT\n"


async def test_recovery_report(tmp_path):
    """The journal is inspectable after an apply."""
    _repo, toolkit, artifact_id, sha = await _generated(tmp_path)
    missing = await toolkit._recovery_report(artifact_id)
    assert missing.error.code == "no_journal"

    await toolkit.writer_apply(artifact_id, sha)
    report = await toolkit._recovery_report(artifact_id)
    assert report.status == "ok"
    assert report.data["state"] == "applied"
    assert {entry["path"] for entry in report.data["entries"]} == {"pkg/__init__.py", "pkg/greeter.py"}
    assert all(entry["state"] == "verified" for entry in report.data["entries"])


async def test_journal_is_retained_as_evidence(tmp_path):
    """The journal is never deleted; only its state changes."""
    repo, toolkit, artifact_id, sha = await _generated(tmp_path)
    await toolkit.writer_apply(artifact_id, sha)
    journal_file = repo / "artifacts" / "tool-optimizations" / artifact_id / "journal.json"
    assert journal_file.is_file()

    await toolkit.writer_apply(artifact_id, sha)  # idempotent re-run
    assert journal_file.is_file()


# --------------------------------------------------------------------------- #
# Source guarantees
# --------------------------------------------------------------------------- #
def test_apply_path_never_uses_mutating_git_verbs():
    """Applying never stages, commits, pushes, resets or checks out."""
    import inspect

    import parrot_tools.tool_optimizations.writer as module

    source = inspect.getsource(module)
    for verb in ('"add"', '"commit"', '"push"', '"checkout"', '"reset"'):
        assert verb not in source, f"forbidden git argv literal in the apply path: {verb}"
