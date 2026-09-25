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
from parrot.tools.filemanager import FileManagerFactory, FileManagerTool, FileManagerToolkit
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


def test_no_msgraph_leak_on_import():
    """Importing parrot.interfaces.file does not load msgraph or the Graph managers (FEAT-603 AC10)."""
    if "msgraph" in sys.modules or "parrot.interfaces.file.graph" in sys.modules:
        pytest.skip("msgraph already loaded by a prior test")
    importlib.reload(shim)
    assert "msgraph" not in sys.modules
    assert "parrot.interfaces.file.graph" not in sys.modules


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


# ── FEAT-603 — SharePoint / OneDrive lazy exports and native factory ────

def test_shim_exports_new_managers_lazily():
    """SharePointFileManager / OneDriveFileManager are the classes from their submodules and are in __all__."""
    from parrot.interfaces.file.sharepoint import SharePointFileManager as _SP_Direct
    from parrot.interfaces.file.onedrive import OneDriveFileManager as _OD_Direct

    assert shim.SharePointFileManager is _SP_Direct
    assert shim.OneDriveFileManager is _OD_Direct
    assert "SharePointFileManager" in shim.__all__
    assert "OneDriveFileManager" in shim.__all__


def test_parrot_tools_file_shim_parity():
    """parrot_tools.file re-exports the same SharePoint/OneDrive classes as the core shim."""
    import parrot_tools.file as tools_shim

    assert tools_shim.SharePointFileManager is shim.SharePointFileManager
    assert tools_shim.OneDriveFileManager is shim.OneDriveFileManager


def test_factory_sharepoint_and_onedrive_native(monkeypatch):
    """FileManagerFactory.create resolves sharepoint/onedrive locally, without I/O at construction time.

    SharePointFileManager / OneDriveFileManager stay abstract (missing copy_file/create_file/download_file/
    get_file_url/upload_file) until the Graph write-ops land (TASK-3752/3753/3754 — out of this task's
    dependency chain, TASK-3758 depends only on TASK-3756/TASK-3757). __abstractmethods__ is cleared for the
    duration of this test only, so the assertion below verifies the factory dispatch itself (module/class
    resolved, kwargs forwarded, no network I/O) without depending on those sibling tasks.
    """
    from parrot.interfaces.file.sharepoint import SharePointFileManager
    from parrot.interfaces.file.onedrive import OneDriveFileManager

    monkeypatch.setattr(SharePointFileManager, "__abstractmethods__", frozenset())
    monkeypatch.setattr(OneDriveFileManager, "__abstractmethods__", frozenset())

    sp = FileManagerFactory.create("sharepoint", site="TeamSite")
    assert isinstance(sp, SharePointFileManager)

    od = FileManagerFactory.create("onedrive", user="me")
    assert isinstance(od, OneDriveFileManager)


def test_factory_unknown_lists_all_keys():
    """The ValueError for an unrecognised manager_type lists all six valid keys."""
    with pytest.raises(ValueError) as ei:
        FileManagerFactory.create("xyz")  # type: ignore[arg-type]
    msg = str(ei.value)
    for key in ("fs", "temp", "s3", "gcs", "sharepoint", "onedrive"):
        assert key in msg


def test_toolkit_literal_accepts_new_types(monkeypatch):
    """FileManagerToolkit accepts the new manager_type literals and builds its tools without network I/O.

    See test_factory_sharepoint_and_onedrive_native for why __abstractmethods__ is cleared here too.
    """
    from parrot.interfaces.file.sharepoint import SharePointFileManager

    monkeypatch.setattr(SharePointFileManager, "__abstractmethods__", frozenset())

    toolkit = FileManagerToolkit(manager_type="sharepoint", site="TeamSite")
    tools = toolkit.get_tools()
    assert len(tools) == 9
