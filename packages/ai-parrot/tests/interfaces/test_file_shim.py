"""Regression tests for the parrot.interfaces.file shim over
navigator.utils.file (FEAT-123 — fileinterface-migration).
"""
import importlib
import sys
from io import BytesIO
from pathlib import Path

import pytest

import parrot.interfaces.file as shim
import navigator.utils.file as upstream
from parrot.interfaces.file import LocalFileManager
from parrot.tools.filemanager import FileManagerFactory, FileManagerTool
from navigator.utils.file.local import LocalFileManager as UpstreamLocal
from navigator.utils.file.tmp import TempFileManager as UpstreamTemp


# ── Identity / shim wiring ──────────────────────────────────────

def test_root_identity():
    """Eagerly-exported symbols are upstream classes."""
    assert shim.FileManagerInterface is upstream.FileManagerInterface
    assert shim.FileMetadata is upstream.FileMetadata
    assert shim.LocalFileManager is upstream.LocalFileManager
    assert shim.TempFileManager is upstream.TempFileManager


def test_no_cloud_sdk_leak_on_import():
    """Importing parrot.interfaces.file does not load aioboto3 / gcs.

    This test must run before test_lazy_identity, which accesses S3FileManager
    and GCSFileManager and thereby loads the cloud SDKs into sys.modules.
    """
    if "aioboto3" in sys.modules or "google.cloud.storage" in sys.modules:
        pytest.skip("cloud SDK already loaded by a prior test")
    importlib.reload(shim)
    assert "aioboto3" not in sys.modules
    assert "google.cloud.storage" not in sys.modules


def test_lazy_identity():
    """S3/GCS lazy attributes resolve to the upstream classes."""
    assert shim.S3FileManager is upstream.S3FileManager
    assert shim.GCSFileManager is upstream.GCSFileManager


def test_submodule_paths_resolve():
    """Submodule imports still work and point at upstream."""
    from parrot.interfaces.file.abstract import (
        FileManagerInterface as A_FMI,
        FileMetadata as A_FM,
    )
    from parrot.interfaces.file.local import LocalFileManager as L_LFM
    from parrot.interfaces.file.tmp import TempFileManager as T_TFM
    from parrot.interfaces.file.s3 import S3FileManager as S_S3
    from parrot.interfaces.file.gcs import GCSFileManager as G_GCS

    assert A_FMI is upstream.FileManagerInterface
    assert A_FM is upstream.FileMetadata
    assert L_LFM is upstream.LocalFileManager
    assert T_TFM is upstream.TempFileManager
    assert S_S3 is upstream.S3FileManager
    assert G_GCS is upstream.GCSFileManager


# ── Behaviour change — create_from_bytes now returns bool ───────

@pytest.mark.asyncio
async def test_create_from_bytes_returns_bool(tmp_path: Path):
    """Upstream contract: bool return, not FileMetadata."""
    fm = LocalFileManager(base_path=tmp_path)
    rv = await fm.create_from_bytes("foo.txt", BytesIO(b"hi"))
    assert rv is True
    assert type(rv) is bool


# ── Parrot-level FileManagerFactory delegates to upstream ───────

def test_factory_fs_returns_upstream_localfilemanager(tmp_path: Path):
    fm = FileManagerFactory.create("fs", base_path=str(tmp_path))
    assert isinstance(fm, UpstreamLocal)


def test_factory_temp_returns_upstream_tempfilemanager():
    fm = FileManagerFactory.create("temp")
    assert isinstance(fm, UpstreamTemp)


def test_factory_unknown_type_raises_valueerror():
    with pytest.raises(ValueError) as ei:
        FileManagerFactory.create("xyz")  # type: ignore[arg-type]
    msg = str(ei.value)
    assert "xyz" in msg or "Unknown" in msg


# ── FileManagerTool.create flow uses get_file_metadata adapter ──

@pytest.mark.asyncio
async def test_filemanager_tool_create_uses_get_metadata(tmp_path: Path):
    tool = FileManagerTool(
        manager_type="fs",
        default_output_dir=str(tmp_path),
        base_path=str(tmp_path),
    )
    res = await tool._execute(
        operation="create",
        path="hello.txt",
        content="hi",
    )
    assert res.success, res.error
    body = res.result
    assert body["created"] is True
    assert body["name"] == "hello.txt"
    assert body["size"] == len("hi".encode("utf-8"))
    assert "content_type" in body
    # Confirm file physically exists at the path reported by get_file_metadata.
    # LocalFileManager resolves paths relative to base_path, so use body["path"]
    # rather than hardcoding tmp_path / "hello.txt".
    actual_path = tmp_path / body["path"]
    assert actual_path.read_bytes() == b"hi"
