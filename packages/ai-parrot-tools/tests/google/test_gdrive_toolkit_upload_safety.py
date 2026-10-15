"""Tests for GoogleDriveToolkit upload_file path confinement and conflict-behavior isolation.

FEAT-690 / TASK-4401 — ledger issue:46cf08490263.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Union
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot_tools.google.drive import GoogleDriveToolkit, _validate_local_source


# ---------------------------------------------------------------------------
# _validate_local_source unit tests
# ---------------------------------------------------------------------------


class TestValidateLocalSource:
    """Direct tests for the path-validation helper."""

    def test_traversal_rejected(self, tmp_path: Path) -> None:
        """AC1: ``../../etc/passwd`` must raise ValueError."""
        with pytest.raises(ValueError, match="escapes the upload root"):
            _validate_local_source("../../etc/passwd", tmp_path)

    def test_absolute_path_rejected(self, tmp_path: Path) -> None:
        """AC2: An absolute path must raise ValueError."""
        with pytest.raises(ValueError, match="must be relative"):
            _validate_local_source("/etc/passwd", str(tmp_path))

    def test_empty_path_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="required"):
            _validate_local_source("", tmp_path)

    def test_nul_byte_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="NUL"):
            _validate_local_source("file\x00.txt", tmp_path)

    def test_drive_qualified_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="drive-qualified"):
            _validate_local_source("C:\\Users\\file.txt", tmp_path)

    def test_valid_subdir_upload(self, tmp_path: Path) -> None:
        """AC3: A valid relative path to an existing file succeeds."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        target = subdir / "file.txt"
        target.write_text("data")
        result = _validate_local_source("subdir/file.txt", tmp_path)
        assert result == target.resolve()

    def test_symlink_escape_rejected(self, tmp_path: Path) -> None:
        """AC4: A symlink pointing outside upload_root is rejected."""
        outside = tmp_path / "outside"
        outside.mkdir()
        secret = outside / "secret.txt"
        secret.write_text("secret")

        root = tmp_path / "root"
        root.mkdir()
        link = root / "escape.txt"
        link.symlink_to(secret)

        with pytest.raises(ValueError, match="escapes the upload root"):
            _validate_local_source("escape.txt", root)

    def test_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            _validate_local_source("nonexistent.txt", tmp_path)

    def test_directory_rejected(self, tmp_path: Path) -> None:
        """Passing a directory path (not a regular file) raises FileNotFoundError."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        with pytest.raises(FileNotFoundError, match="not a regular file"):
            _validate_local_source("subdir", tmp_path)


# ---------------------------------------------------------------------------
# Toolkit-level integration tests (mocked manager)
# ---------------------------------------------------------------------------


def _fake_metadata(**overrides: Any) -> MagicMock:
    """Build a minimal FileMetadata-like mock."""
    defaults = {"name": "test.txt", "path": "dest/test.txt", "size": 42,
                "content_type": "text/plain", "url": "https://drive/test.txt"}
    defaults.update(overrides)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _build_toolkit(upload_root: Union[str, Path], manager: Any = None) -> GoogleDriveToolkit:
    """Build a toolkit with a mocked manager and explicit upload_root.

    When *manager* is supplied, its attributes are NOT overwritten — the
    caller owns the mock configuration.
    """
    if manager is None:
        mgr = MagicMock()
        mgr.conflict_behavior = "replace"
        mgr.upload_file = AsyncMock(return_value=_fake_metadata())
    else:
        mgr = manager
    tk = GoogleDriveToolkit(manager=mgr, upload_root=upload_root)
    # Skip the _open lifecycle — manager is already injected.
    tk._opened = True
    return tk


class TestUploadFileConfinement:
    """Toolkit.upload_file path confinement."""

    @pytest.mark.asyncio
    async def test_traversal_via_toolkit(self, tmp_path: Path) -> None:
        """AC1 at the toolkit boundary."""
        tk = _build_toolkit(tmp_path)
        with pytest.raises(ValueError, match="escapes"):
            await tk.upload_file("../../etc/passwd", "dest")

    @pytest.mark.asyncio
    async def test_absolute_via_toolkit(self, tmp_path: Path) -> None:
        """AC2 at the toolkit boundary."""
        tk = _build_toolkit(tmp_path)
        with pytest.raises(ValueError, match="must be relative"):
            await tk.upload_file("/etc/passwd", "dest")

    @pytest.mark.asyncio
    async def test_valid_upload(self, tmp_path: Path) -> None:
        """AC3: Valid file inside upload_root succeeds."""
        target = tmp_path / "report.txt"
        target.write_text("data")
        tk = _build_toolkit(tmp_path)
        result = await tk.upload_file("report.txt", "dest/report.txt")
        assert result["uploaded"] is True
        tk._manager.upload_file.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_symlink_escape_via_toolkit(self, tmp_path: Path) -> None:
        """AC4 at the toolkit boundary."""
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("secret")
        root = tmp_path / "root"
        root.mkdir()
        (root / "link.txt").symlink_to(outside / "secret.txt")
        tk = _build_toolkit(root)
        with pytest.raises(ValueError, match="escapes"):
            await tk.upload_file("link.txt", "dest")


class TestConflictBehaviorIsolation:
    """AC5: Concurrent uploads with different conflict_behavior do not interfere."""

    @pytest.mark.asyncio
    async def test_concurrent_conflict_behavior(self, tmp_path: Path) -> None:
        """Two concurrent uploads with different policies must not corrupt each other."""
        file_a = tmp_path / "a.txt"
        file_b = tmp_path / "b.txt"
        file_a.write_text("a")
        file_b.write_text("b")

        observed_behaviors: list[str] = []

        async def _recording_upload(source: Any, destination: str) -> MagicMock:
            """Record the manager's conflict_behavior at call time."""
            observed_behaviors.append(mgr.conflict_behavior)
            # Simulate async I/O to give the event loop a chance to interleave.
            await asyncio.sleep(0.01)
            return _fake_metadata()

        mgr = MagicMock()
        mgr.conflict_behavior = "replace"
        mgr.upload_file = AsyncMock(side_effect=_recording_upload)
        tk = _build_toolkit(tmp_path, manager=mgr)

        await asyncio.gather(
            tk.upload_file("a.txt", "dest/a.txt", conflict_behavior="rename"),
            tk.upload_file("b.txt", "dest/b.txt", conflict_behavior="fail"),
        )

        # Under the lock, each call must see its own policy, never the other's.
        assert set(observed_behaviors) == {"rename", "fail"}

    @pytest.mark.asyncio
    async def test_behavior_restored_on_error(self, tmp_path: Path) -> None:
        """The manager's conflict_behavior is restored even when upload raises."""
        target = tmp_path / "boom.txt"
        target.write_text("x")

        mgr = MagicMock()
        mgr.conflict_behavior = "replace"
        mgr.upload_file = AsyncMock(side_effect=RuntimeError("upload failed"))
        tk = _build_toolkit(tmp_path, manager=mgr)

        with pytest.raises(RuntimeError, match="upload failed"):
            await tk.upload_file("boom.txt", "dest", conflict_behavior="rename")

        assert mgr.conflict_behavior == "replace"


class TestDefaultUploadRoot:
    """AC6: When upload_root is not supplied, it defaults to download_dir."""

    def test_default_upload_root_is_download_dir(self, tmp_path: Path) -> None:
        mgr = MagicMock()
        mgr.conflict_behavior = "replace"
        tk = GoogleDriveToolkit(manager=mgr, download_dir=tmp_path)
        assert tk.upload_root == tmp_path.resolve()

    def test_explicit_upload_root_overrides(self, tmp_path: Path) -> None:
        root = tmp_path / "custom"
        root.mkdir()
        mgr = MagicMock()
        mgr.conflict_behavior = "replace"
        tk = GoogleDriveToolkit(manager=mgr, download_dir=tmp_path, upload_root=root)
        assert tk.upload_root == root.resolve()
