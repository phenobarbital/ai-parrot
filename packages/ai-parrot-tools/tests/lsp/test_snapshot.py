"""Unit tests for FEAT-580 M1 workspace snapshots and position conversion.

Every test either exercises a real, disposable Git worktree under
``tmp_path`` (never the developer's real checkout) or is pure in-memory
position-math with no I/O at all.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
from pathlib import Path

import pytest

from parrot_tools.lsp import snapshot
from parrot_tools.lsp.models import LSPConfig, LSPFailure


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _config(repo_root: Path, **overrides: object) -> LSPConfig:
    fields: dict[str, object] = {"repo_root": repo_root, "environment_id": "env-1"}
    fields.update(overrides)
    return LSPConfig(**fields)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A small, real Git worktree with two tracked Python files."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "__init__.py").write_text("")
    (repo / "pkg" / "mod.py").write_text("value = 1\n")
    (repo / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _matching_pids(needle: bytes) -> set[int]:
    """Return the PIDs of live processes whose cmdline contains ``needle``."""
    pids: set[int] = set()
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/cmdline", "rb") as handle:
                cmdline = handle.read()
        except OSError:
            continue
        if needle in cmdline:
            pids.add(int(entry))
    return pids


class TestWorkspaceConfinementAndRaces:
    @pytest.mark.asyncio
    async def test_workspace_confinement_and_races(
        self, git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = _config(git_repo)

        # -- Traversal: a requested path escaping repo_root is rejected. --
        with pytest.raises(LSPFailure) as excinfo:
            await snapshot.capture_workspace(config, ["../evil.py"])
        assert excinfo.value.code == "path_outside_root"

        # -- Escaping symlink: an untracked, non-ignored symlink whose --
        # -- target resolves outside repo_root fails the whole capture. --
        outside = tmp_path / "outside.py"
        outside.write_text("x = 1\n")
        escape_link = git_repo / "escape.py"
        escape_link.symlink_to(outside)
        with pytest.raises(LSPFailure) as excinfo:
            await snapshot.capture_workspace(config, [])
        assert excinfo.value.code == "path_outside_root"
        escape_link.unlink()

        # -- FIFO: an unsupported target type is rejected without hanging. --
        # Git never lists a *new* FIFO as untracked (it skips special files
        # during directory scans), so this replaces an already-tracked
        # file's working-tree content — `git ls-files` still reports the
        # tracked path from the index regardless of the on-disk file type.
        fifo_target = git_repo / "pkg" / "fifo_target.py"
        fifo_target.write_text("z = 1\n")
        _git(git_repo, "add", "pkg/fifo_target.py")
        _git(git_repo, "commit", "-q", "-m", "add fifo target")
        fifo_target.unlink()
        os.mkfifo(fifo_target)
        try:
            with pytest.raises(LSPFailure) as excinfo:
                await snapshot.capture_workspace(config, [])
            assert excinfo.value.code == "invalid_request"
        finally:
            fifo_target.unlink()
            fifo_target.write_text("z = 1\n")

        # -- Ignored/unlisted target: explicitly rejected, not silently --
        # -- dropped, when requested by the caller. --
        (git_repo / ".gitignore").write_text("ignored.py\n")
        _git(git_repo, "add", ".gitignore")
        _git(git_repo, "commit", "-q", "-m", "ignore rule")
        (git_repo / "ignored.py").write_text("z = 1\n")
        try:
            with pytest.raises(LSPFailure) as excinfo:
                await snapshot.capture_workspace(config, ["ignored.py"])
            assert excinfo.value.code == "invalid_request"
        finally:
            (git_repo / "ignored.py").unlink()

        # -- Deleted tracked files become tombstones, not silent absence. --
        tracked_target = git_repo / "pkg" / "mod.py"
        tracked_target.unlink()
        snap = await snapshot.capture_workspace(config, [])
        assert "pkg/mod.py" in snap.missing_paths
        assert "pkg/mod.py" not in snap.file_hashes
        with pytest.raises(LSPFailure) as excinfo:
            await snapshot.capture_workspace(config, ["pkg/mod.py"])
        assert excinfo.value.code == "file_missing"
        _git(git_repo, "checkout", "--", "pkg/mod.py")

        # -- Untracked, non-ignored files are discoverable and their exact --
        # -- text is returned only for the paths actually requested. --
        (git_repo / "pkg" / "new_mod.py").write_text("answer = 42\n")
        snap = await snapshot.capture_workspace(config, ["pkg/new_mod.py"])
        assert "pkg/new_mod.py" in snap.file_hashes
        assert snap.requested_text["pkg/new_mod.py"] == "answer = 42\n"
        assert "pkg/mod.py" not in snap.requested_text
        (git_repo / "pkg" / "new_mod.py").unlink()

        # -- Successful stable read: open/fstat/read/fstat with no race --
        # -- produces a hash matching a plain direct read. --
        canonical_root = os.path.realpath(str(git_repo))
        result = snapshot._process_target(
            str(git_repo), "pkg/mod.py", canonical_root, need_text=True, max_file_bytes=1024 * 1024
        )
        assert "error" not in result
        assert result["sha256"] == hashlib.sha256(tracked_target.read_bytes()).hexdigest()
        assert result["text"] == tracked_target.read_text()

        # -- Adversarial race: content changes between the two fstat calls --
        # -- of the stable open/fstat/read/fstat sequence is detected. --
        race_file = tmp_path / "race.py"
        race_file.write_bytes(b"a" * 10)
        original_fstat = os.fstat
        call_count = {"n": 0}

        def flaky_fstat(fd: int):
            call_count["n"] += 1
            if call_count["n"] == 2:
                # Mutate via the path, not the (read-only) fd under test —
                # os.ftruncate requires a writable fd, but a real concurrent
                # writer would use its own fd/path just like this.
                os.truncate(str(race_file), 5)
            return original_fstat(fd)

        monkeypatch.setattr(os, "fstat", flaky_fstat)
        race_result = snapshot._process_target(
            str(tmp_path), "race.py", os.path.realpath(str(tmp_path)), need_text=False, max_file_bytes=1024
        )
        assert race_result["error"] == "source_changed"


class TestWorkspaceDigestDependencyChange:
    @pytest.mark.asyncio
    async def test_workspace_digest_dependency_change(self, git_repo: Path) -> None:
        config = _config(git_repo)

        first = await snapshot.capture_workspace(config, [])
        second = await snapshot.capture_workspace(config, [])
        assert first.digest == second.digest  # idempotent when nothing changed

        # A same-size edit to a tracked source file still changes the digest
        # (content hash, not just size, drives freshness).
        mod_path = git_repo / "pkg" / "mod.py"
        original = mod_path.read_text()
        replacement = "value = 2\n"
        assert len(replacement) == len(original)
        mod_path.write_text(replacement)
        edited = await snapshot.capture_workspace(config, [])
        assert edited.digest != first.digest
        assert edited.file_hashes["pkg/mod.py"] != first.file_hashes["pkg/mod.py"]
        mod_path.write_text(original)
        restored = await snapshot.capture_workspace(config, [])
        assert restored.digest == first.digest

        # A change to a non-target dependency/config file (not requested by
        # the caller at all) still invalidates the workspace digest.
        pyproject_path = git_repo / "pyproject.toml"
        original_pyproject = pyproject_path.read_text()
        pyproject_path.write_text(original_pyproject + "\n[tool.extra]\nflag = true\n")
        dep_changed = await snapshot.capture_workspace(config, [])
        assert dep_changed.digest != first.digest
        pyproject_path.write_text(original_pyproject)

        # A change to the effective configuration identity (not file
        # content at all) also changes the digest.
        other_env_config = _config(git_repo, environment_id="env-2")
        other_env = await snapshot.capture_workspace(other_env_config, [])
        assert other_env.digest != first.digest
        assert other_env.config_digest != first.config_digest


class TestUnicodePositions:
    def test_unicode_positions(self) -> None:
        text = "abc\ndef\n"

        # -- Successful ASCII round trip. --
        assert snapshot.to_lsp_position(text, 1, 1) == {"line": 0, "character": 0}
        assert snapshot.to_lsp_position(text, 2, 3) == {"line": 1, "character": 2}

        # -- CRLF: splitlines() treats "\r\n" as a single terminator. --
        crlf_text = "abc\r\ndef\r\n"
        assert snapshot.to_lsp_position(crlf_text, 2, 1) == {"line": 1, "character": 0}

        # -- Tabs count as one Unicode code point, not a display width. --
        tab_text = "a\tbc\n"
        assert snapshot.to_lsp_position(tab_text, 1, 3) == {"line": 0, "character": 2}

        # -- Astral characters occupy 2 UTF-16 code units. --
        astral_text = "a\U0001f600b\n"  # 'a', emoji, 'b'
        assert snapshot.to_lsp_position(astral_text, 1, 1) == {"line": 0, "character": 0}
        assert snapshot.to_lsp_position(astral_text, 1, 2) == {"line": 0, "character": 1}  # before emoji
        assert snapshot.to_lsp_position(astral_text, 1, 3) == {"line": 0, "character": 3}  # after emoji

        # -- EOF: one line past the end, column 1, is a valid empty --
        # -- trailing position; anything further is out of range. --
        assert snapshot.to_lsp_position(text, 3, 1) == {"line": 2, "character": 0}
        with pytest.raises(LSPFailure) as excinfo:
            snapshot.to_lsp_position(text, 3, 2)
        assert excinfo.value.code == "position_out_of_range"
        with pytest.raises(LSPFailure) as excinfo:
            snapshot.to_lsp_position(text, 4, 1)
        assert excinfo.value.code == "position_out_of_range"

        # -- Invalid (non-positive) lines/columns are rejected. --
        with pytest.raises(LSPFailure) as excinfo:
            snapshot.to_lsp_position(text, 0, 1)
        assert excinfo.value.code == "position_out_of_range"
        with pytest.raises(LSPFailure) as excinfo:
            snapshot.to_lsp_position(text, 1, 0)
        assert excinfo.value.code == "position_out_of_range"

        # -- Inverse range normalization round-trips for the same fixture. --
        lsp_range = {"start": {"line": 1, "character": 0}, "end": {"line": 1, "character": 3}}
        source_range = snapshot.from_lsp_range(text, "pkg/mod.py", lsp_range)
        assert source_range.path == "pkg/mod.py"
        assert (source_range.start_line, source_range.start_column) == (2, 1)
        assert (source_range.end_line, source_range.end_column) == (2, 4)

        # -- Adversarial: a half-surrogate server range that splits an --
        # -- astral code point is rejected, not silently truncated. --
        with pytest.raises(LSPFailure) as excinfo:
            snapshot.from_lsp_range(
                astral_text,
                "pkg/mod.py",
                {"start": {"line": 0, "character": 1}, "end": {"line": 0, "character": 2}},
            )
        assert excinfo.value.code == "protocol_error"

        # -- Adversarial: a server position past the end of a line is --
        # -- rejected on the inverse path too. --
        with pytest.raises(LSPFailure) as excinfo:
            snapshot.from_lsp_range(
                text,
                "pkg/mod.py",
                {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 99}},
            )
        assert excinfo.value.code == "position_out_of_range"


class TestWorkerCancelReapsProcess:
    @pytest.mark.asyncio
    async def test_worker_cancel_reaps_process(
        self, git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # -- Successful case: an ordinary, fast manifest pass completes --
        # -- and leaves nothing running. --
        tracked = await snapshot._run_git(git_repo, ["ls-files", "-z"])
        assert b"pkg/mod.py" in tracked

        bin_dir = tmp_path / "shim_bin"
        bin_dir.mkdir()

        # -- Adversarial case 1: cancelling a slow git manifest pass --
        # -- kills and reaps its child instead of leaking it. --
        git_shim = bin_dir / "git"
        git_shim.write_text("#!/bin/sh\nexec sleep 12345\n")
        git_shim.chmod(0o755)
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

        before = _matching_pids(b"12345")
        git_task = asyncio.ensure_future(snapshot._run_git(git_repo, ["ls-files", "-z"]))
        await asyncio.sleep(0.2)
        during = _matching_pids(b"12345") - before
        assert during, "expected the slow git shim's sleep child to be running"

        git_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await git_task
        await asyncio.sleep(0.1)
        after = _matching_pids(b"12345")
        assert not (during & after), "the cancelled git manifest worker's child was not reaped"

        # -- Adversarial case 2: cancelling a slow hashing/reading worker --
        # -- kills and reaps its child instead of leaking it. --
        worker_shim = bin_dir / "python_worker_shim"
        worker_shim.write_text("#!/bin/sh\nexec sleep 54321\n")
        worker_shim.chmod(0o755)
        monkeypatch.setattr(snapshot.sys, "executable", str(worker_shim))

        canonical_root = Path(os.path.realpath(str(git_repo)))
        before2 = _matching_pids(b"54321")
        worker_task = asyncio.ensure_future(snapshot._run_snapshot_worker(git_repo, canonical_root, [], set()))
        await asyncio.sleep(0.2)
        during2 = _matching_pids(b"54321") - before2
        assert during2, "expected the slow snapshot worker shim's sleep child to be running"

        worker_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker_task
        await asyncio.sleep(0.1)
        after2 = _matching_pids(b"54321")
        assert not (during2 & after2), "the cancelled snapshot worker's child was not reaped"
