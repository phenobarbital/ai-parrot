"""Unit tests for FileManagerToolkit (FEAT-127, TASK-872).

The underlying navigator-api (2.14.10) does not yet expose
FileManagerInterface, LocalFileManager, FileMetadata, or FileManagerFactory
from ``navigator.utils.file``.  These tests use ``unittest.mock`` to patch
the missing symbols into ``sys.modules`` BEFORE importing the filemanager
module, so the entire test suite runs without requiring a newer navigator
version.
"""
from __future__ import annotations

import sys
import types
import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Bootstrap: inject mock navigator symbols before parrot imports them
# ---------------------------------------------------------------------------

def _make_navigator_mock() -> types.ModuleType:
    """Return a fake ``navigator.utils.file`` module with the expected API."""

    class _FileMetadata:
        def __init__(self, name, path, size=0, content_type="application/octet-stream", url=None, modified_at=None):
            self.name = name
            self.path = path
            self.size = size
            self.content_type = content_type
            self.url = url
            self.modified_at = modified_at or datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)

    class _FileManagerInterface:
        """Minimal async interface that the real upstream exposes."""
        async def list_files(self, path: str, pattern: str) -> list:
            return []
        async def upload_file(self, source: Path, destination: str) -> _FileMetadata:
            raise NotImplementedError
        async def download_file(self, path: str, dest: Path) -> Path:
            raise NotImplementedError
        async def copy_file(self, source: str, destination: str) -> _FileMetadata:
            raise NotImplementedError
        async def delete_file(self, path: str) -> bool:
            raise NotImplementedError
        async def exists(self, path: str) -> bool:
            raise NotImplementedError
        async def get_file_url(self, path: str, expiry: int) -> str:
            raise NotImplementedError
        async def get_file_metadata(self, path: str) -> _FileMetadata:
            raise NotImplementedError
        async def create_from_bytes(self, path: str, data: BytesIO) -> bool:
            raise NotImplementedError

    class _LocalFileManager(_FileManagerInterface):
        pass

    class _TempFileManager(_FileManagerInterface):
        pass

    class _FileManagerFactory:
        @staticmethod
        def create(manager_type: str, **kwargs) -> _FileManagerInterface:
            return _TempFileManager()

    nav_mod = types.ModuleType("navigator.utils.file")
    nav_mod.FileManagerInterface = _FileManagerInterface
    nav_mod.FileMetadata = _FileMetadata
    nav_mod.LocalFileManager = _LocalFileManager
    nav_mod.TempFileManager = _TempFileManager
    nav_mod.FileManagerFactory = _FileManagerFactory
    # Re-expose the real cloud managers if they are already loaded
    try:
        from navigator.utils.file import GCSFileManager
        nav_mod.GCSFileManager = GCSFileManager
    except ImportError:
        nav_mod.GCSFileManager = MagicMock()
    try:
        from navigator.utils.file import S3FileManager
        nav_mod.S3FileManager = S3FileManager
    except ImportError:
        nav_mod.S3FileManager = MagicMock()

    return nav_mod


# Patch sys.modules BEFORE importing parrot.tools.filemanager.
#
# The installed navigator-api 2.14.10 does NOT export FileManagerInterface,
# FileMetadata, LocalFileManager, or FileManagerFactory from
# navigator.utils.file.  We must REPLACE (not setdefault) the cached real
# module so that when parrot.interfaces.file re-imports, it gets our mock.
#
# We also purge any previously-cached (and broken) imports of
# parrot.interfaces.file and parrot.tools.filemanager so Python re-imports
# them fresh with the patched navigator module in place.
#
# ISOLATION: We save the original module reference before patching so it
# can be restored after the test session, preventing contamination of other
# test modules that run later in the same pytest worker.
_original_nav_module = sys.modules.get("navigator.utils.file")
_nav_mock = _make_navigator_mock()
sys.modules["navigator.utils.file"] = _nav_mock  # replace, not setdefault

for _key in list(sys.modules):
    if "parrot.interfaces.file" in _key or "parrot.tools.filemanager" in _key or "parrot.interfaces" == _key:
        del sys.modules[_key]

# Now safe to import the real module
from parrot.tools.filemanager import (  # noqa: E402
    FileManagerFactory,
    FileManagerTool,
    FileManagerToolkit,
)
from parrot.tools import FileManagerToolkit as FileManagerToolkitFromInit  # noqa: E402
from parrot.tools.toolkit import AbstractToolkit  # noqa: E402


# ---------------------------------------------------------------------------
# sys.modules cleanup — restore original navigator module after the session
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True, scope="session")
def _restore_navigator_module_after_session():
    """Restore navigator.utils.file in sys.modules when the session ends.

    The module-level patch above replaces the real navigator module for the
    lifetime of this test module.  Without this fixture, tests that happen to
    run *after* this file in the same pytest worker (e.g. if collection order
    changes) would silently receive the mock instead of the real module.
    """
    yield
    if _original_nav_module is not None:
        sys.modules["navigator.utils.file"] = _original_nav_module
    else:
        sys.modules.pop("navigator.utils.file", None)


# ---------------------------------------------------------------------------
# Helpers — in-memory file manager for operation tests
# ---------------------------------------------------------------------------

class _FileMeta:
    """Simple file metadata object returned by _InMemoryFileManager."""

    def __init__(self, path: str, data: bytes = b""):
        self.name = Path(path).name
        self.path = path
        self.size = len(data)
        self.content_type = "text/plain"
        self.url = f"file://{path}"
        self.modified_at = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


class _InMemoryFileManager:
    """Async in-memory file manager that implements the FileManagerInterface API."""

    def __init__(self):
        self._files: dict[str, bytes] = {}

    def _meta(self, path: str) -> _FileMeta:
        return _FileMeta(path, self._files.get(path, b""))

    async def list_files(self, path: str, pattern: str) -> list:
        import fnmatch
        return [
            self._meta(p)
            for p in self._files
            if fnmatch.fnmatch(Path(p).name, pattern)
            and (not path or p.startswith(path))
        ]

    async def upload_file(self, source: Path, destination: str) -> Any:
        data = source.read_bytes()
        self._files[destination] = data
        return self._meta(destination)

    async def download_file(self, path: str, dest: Path) -> Path:
        data = self._files.get(path, b"")
        dest.write_bytes(data)
        return dest

    async def copy_file(self, source: str, destination: str) -> Any:
        self._files[destination] = self._files.get(source, b"")
        return self._meta(destination)

    async def delete_file(self, path: str) -> bool:
        if path in self._files:
            del self._files[path]
            return True
        return False

    async def exists(self, path: str) -> bool:
        return path in self._files

    async def get_file_url(self, path: str, expiry: int) -> str:
        return f"file://{path}?expiry={expiry}"

    async def get_file_metadata(self, path: str) -> Any:
        return self._meta(path)

    async def create_from_bytes(self, path: str, data: BytesIO) -> bool:
        self._files[path] = data.read()
        return True


def _make_toolkit(tmp_path: Path, **kwargs) -> FileManagerToolkit:
    """Create a FileManagerToolkit backed by the in-memory manager."""
    tk = FileManagerToolkit(
        manager_type="temp",
        default_output_dir=str(tmp_path),
        **kwargs,
    )
    # Replace the real manager with our in-memory implementation
    tk.manager = _InMemoryFileManager()
    return tk


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestToolkitInit:
    """Toolkit initialisation — structure and defaults."""

    def test_inherits_abstract_toolkit(self):
        tk = FileManagerToolkit(manager_type="temp")
        assert isinstance(tk, AbstractToolkit)

    def test_tool_prefix(self):
        tk = FileManagerToolkit(manager_type="temp")
        assert tk.tool_prefix == "fs"

    def test_default_max_file_size(self):
        tk = FileManagerToolkit(manager_type="temp")
        assert tk.max_file_size == 100 * 1024 * 1024

    def test_custom_max_file_size(self):
        tk = FileManagerToolkit(manager_type="temp", max_file_size=1024)
        assert tk.max_file_size == 1024

    def test_auto_create_dirs_default(self):
        tk = FileManagerToolkit(manager_type="temp")
        assert tk.auto_create_dirs is True

    def test_all_operations_allowed_by_default(self):
        tk = FileManagerToolkit(manager_type="temp")
        expected = {"list", "upload", "download", "copy", "delete", "exists", "get_url", "get_metadata", "create"}
        assert tk.allowed_operations == expected


class TestToolGeneration:
    """Tool auto-generation from public async methods."""

    def test_tool_count_default(self, tmp_path):
        tk = _make_toolkit(tmp_path)
        assert len(tk.get_tools()) == 9

    def test_tool_names(self, tmp_path):
        tk = _make_toolkit(tmp_path)
        names = set(tk.list_tool_names())
        expected = {
            "fs_list_files", "fs_upload_file", "fs_download_file",
            "fs_copy_file", "fs_delete_file", "fs_file_exists",
            "fs_get_file_url", "fs_get_file_metadata", "fs_create_file",
        }
        assert names == expected

    def test_allowed_operations_filter_three(self):
        tk = FileManagerToolkit(
            manager_type="temp",
            allowed_operations={"list", "create", "exists"},
        )
        tk.manager = _InMemoryFileManager()
        names = set(tk.list_tool_names())
        assert names == {"fs_list_files", "fs_create_file", "fs_file_exists"}

    def test_allowed_operations_single(self):
        tk = FileManagerToolkit(
            manager_type="temp",
            allowed_operations={"delete"},
        )
        tk.manager = _InMemoryFileManager()
        assert set(tk.list_tool_names()) == {"fs_delete_file"}

    def test_allowed_operations_unknown_key_raises(self):
        """Unknown operation key raises ValueError immediately."""
        with pytest.raises(ValueError, match="unknown operation"):
            FileManagerToolkit(
                manager_type="temp",
                allowed_operations={"list", "creat"},  # typo: "creat" not "create"
            )

    def test_all_operations_in_full_toolkit(self, tmp_path):
        tk = _make_toolkit(tmp_path)
        tools = tk.get_tools()
        # No duplicates
        names = [t.name for t in tools]
        assert len(names) == len(set(names))


class TestSchemaCorrectness:
    """Each tool's schema should contain ONLY its own parameters."""

    def test_create_file_schema_fields(self, tmp_path):
        tk = _make_toolkit(tmp_path)
        tool = tk.get_tool("fs_create_file")
        assert tool is not None
        schema = tool.get_schema()
        props = set(schema["parameters"]["properties"].keys())
        assert "path" in props
        assert "content" in props
        assert "encoding" in props
        # Must NOT have dispatch field or unrelated fields
        assert "operation" not in props
        assert "source_path" not in props
        assert "destination_name" not in props

    def test_list_files_schema_fields(self, tmp_path):
        tk = _make_toolkit(tmp_path)
        tool = tk.get_tool("fs_list_files")
        assert tool is not None
        schema = tool.get_schema()
        props = set(schema["parameters"]["properties"].keys())
        assert "path" in props
        assert "pattern" in props
        assert "content" not in props
        assert "operation" not in props

    def test_upload_file_schema_fields(self, tmp_path):
        tk = _make_toolkit(tmp_path)
        tool = tk.get_tool("fs_upload_file")
        assert tool is not None
        schema = tool.get_schema()
        props = set(schema["parameters"]["properties"].keys())
        assert "source_path" in props
        assert "destination" in props
        assert "destination_name" in props
        assert "operation" not in props

    def test_delete_file_schema_fields(self, tmp_path):
        tk = _make_toolkit(tmp_path)
        tool = tk.get_tool("fs_delete_file")
        schema = tool.get_schema()
        props = set(schema["parameters"]["properties"].keys())
        assert "path" in props
        assert "content" not in props
        assert "pattern" not in props

    def test_file_exists_schema_fields(self, tmp_path):
        tk = _make_toolkit(tmp_path)
        tool = tk.get_tool("fs_file_exists")
        schema = tool.get_schema()
        props = set(schema["parameters"]["properties"].keys())
        assert "path" in props

    def test_get_file_url_schema_fields(self, tmp_path):
        tk = _make_toolkit(tmp_path)
        tool = tk.get_tool("fs_get_file_url")
        schema = tool.get_schema()
        props = set(schema["parameters"]["properties"].keys())
        assert "path" in props
        assert "expiry_seconds" in props


class TestOperations:
    """Verify each of the 9 toolkit methods executes and returns expected dict."""

    @pytest.mark.asyncio
    async def test_create_file_returns_correct_keys(self, tmp_path):
        tk = _make_toolkit(tmp_path)
        result = await tk.create_file(path="test.txt", content="hello world")
        assert result["created"] is True
        assert "name" in result
        assert "path" in result
        assert "size" in result

    @pytest.mark.asyncio
    async def test_create_and_exists(self, tmp_path):
        tk = _make_toolkit(tmp_path)
        result = await tk.create_file(path="greet.txt", content="hello")
        assert result["created"] is True
        # Now check existence using the resolved path
        resolved = result["path"]
        exists_result = await tk.file_exists(path=resolved)
        assert exists_result["exists"] is True

    @pytest.mark.asyncio
    async def test_file_exists_false_for_missing(self, tmp_path):
        tk = _make_toolkit(tmp_path)
        result = await tk.file_exists(path="nonexistent.txt")
        assert result["exists"] is False

    @pytest.mark.asyncio
    async def test_delete_file(self, tmp_path):
        tk = _make_toolkit(tmp_path)
        await tk.create_file(path="to_delete.txt", content="bye")
        # Resolve the path to match what the manager stores
        resolved = tk._resolve_output_path("to_delete.txt")
        result = await tk.delete_file(path=resolved)
        assert result["deleted"] is True

    @pytest.mark.asyncio
    async def test_list_files_empty(self, tmp_path):
        tk = _make_toolkit(tmp_path)
        result = await tk.list_files(path="")
        assert "files" in result
        assert "count" in result
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_list_files_after_create(self, tmp_path):
        tk = _make_toolkit(tmp_path)
        await tk.create_file(path="a.txt", content="aaa")
        await tk.create_file(path="b.txt", content="bbb")
        result = await tk.list_files(path="", pattern="*.txt")
        assert result["count"] == 2

    @pytest.mark.asyncio
    async def test_copy_file(self, tmp_path):
        tk = _make_toolkit(tmp_path)
        await tk.create_file(path="src.txt", content="data")
        src = tk._resolve_output_path("src.txt")
        dst = tk._resolve_output_path("dst.txt")
        result = await tk.copy_file(source=src, destination=dst)
        assert result["copied"] is True
        assert result["source"] == src
        assert result["destination"] == dst

    @pytest.mark.asyncio
    async def test_get_file_url(self, tmp_path):
        tk = _make_toolkit(tmp_path)
        await tk.create_file(path="share.txt", content="share me")
        resolved = tk._resolve_output_path("share.txt")
        result = await tk.get_file_url(path=resolved, expiry_seconds=7200)
        assert "url" in result
        assert result["expiry_seconds"] == 7200
        assert result["path"] == resolved

    @pytest.mark.asyncio
    async def test_get_file_metadata(self, tmp_path):
        tk = _make_toolkit(tmp_path)
        await tk.create_file(path="meta.txt", content="content")
        resolved = tk._resolve_output_path("meta.txt")
        result = await tk.get_file_metadata(path=resolved)
        assert "name" in result
        assert "path" in result
        assert "size" in result
        assert "content_type" in result

    @pytest.mark.asyncio
    async def test_download_file(self, tmp_path):
        tk = _make_toolkit(tmp_path)
        # Put something into the manager
        resolved = tk._resolve_output_path("remote.txt")
        tk.manager._files[resolved] = b"remote content"
        dest = str(tmp_path / "local.txt")
        result = await tk.download_file(path=resolved, destination=dest)
        assert result["downloaded"] is True
        assert result["source"] == resolved


class TestSizeLimits:
    """max_file_size enforcement on create_file and upload_file."""

    @pytest.mark.asyncio
    async def test_create_file_size_exceeded_raises(self, tmp_path):
        tk = _make_toolkit(tmp_path, max_file_size=10)
        with pytest.raises(ValueError, match="exceeds maximum"):
            await tk.create_file(path="big.txt", content="x" * 100)

    @pytest.mark.asyncio
    async def test_create_file_at_limit_succeeds(self, tmp_path):
        tk = _make_toolkit(tmp_path, max_file_size=5)
        result = await tk.create_file(path="exact.txt", content="hello")
        assert result["created"] is True

    @pytest.mark.asyncio
    async def test_upload_file_size_exceeded_raises(self, tmp_path):
        tk = _make_toolkit(tmp_path, max_file_size=5)
        # Create a 10-byte source file
        src = tmp_path / "large_upload.txt"
        src.write_bytes(b"0" * 10)
        with pytest.raises(ValueError, match="exceeds maximum"):
            await tk.upload_file(source_path=str(src))


class TestValidation:
    """Input validation raises ValueError for missing required params."""

    @pytest.mark.asyncio
    async def test_create_file_no_path(self, tmp_path):
        tk = _make_toolkit(tmp_path)
        with pytest.raises(ValueError):
            await tk.create_file(path="", content="content")

    @pytest.mark.asyncio
    async def test_create_file_no_content(self, tmp_path):
        tk = _make_toolkit(tmp_path)
        with pytest.raises(ValueError):
            await tk.create_file(path="file.txt", content="")

    @pytest.mark.asyncio
    async def test_delete_file_no_path(self, tmp_path):
        tk = _make_toolkit(tmp_path)
        with pytest.raises(ValueError):
            await tk.delete_file(path="")

    @pytest.mark.asyncio
    async def test_file_exists_no_path(self, tmp_path):
        tk = _make_toolkit(tmp_path)
        with pytest.raises(ValueError):
            await tk.file_exists(path="")

    @pytest.mark.asyncio
    async def test_copy_file_no_source(self, tmp_path):
        tk = _make_toolkit(tmp_path)
        with pytest.raises(ValueError):
            await tk.copy_file(source="", destination="dst.txt")

    @pytest.mark.asyncio
    async def test_copy_file_no_destination(self, tmp_path):
        tk = _make_toolkit(tmp_path)
        with pytest.raises(ValueError):
            await tk.copy_file(source="src.txt", destination="")

    @pytest.mark.asyncio
    async def test_download_file_no_path(self, tmp_path):
        tk = _make_toolkit(tmp_path)
        with pytest.raises(ValueError):
            await tk.download_file(path="")


class TestBackwardCompat:
    """FileManagerTool and FileManagerFactory remain importable and functional."""

    def test_filemanagertool_importable(self):
        assert FileManagerTool is not None

    def test_filemanagertoolkit_importable(self):
        assert FileManagerToolkit is not None

    def test_filemanagertoolkit_from_parrot_tools(self):
        """from parrot.tools import FileManagerToolkit works."""
        assert FileManagerToolkitFromInit is not None
        assert FileManagerToolkitFromInit is FileManagerToolkit

    def test_filemanagertool_has_deprecation_notice(self):
        """FileManagerTool docstring contains a deprecation warning."""
        assert "deprecated" in (FileManagerTool.__doc__ or "").lower()

    def test_filemanagerfactory_importable(self):
        assert FileManagerFactory is not None

    def test_toolkit_is_not_abstracttool(self):
        """FileManagerToolkit should NOT be an AbstractTool subclass."""
        from parrot.tools.abstract import AbstractTool
        assert not issubclass(FileManagerToolkit, AbstractTool)


class TestRegistryEntry:
    """parrot_tools.TOOL_REGISTRY contains both legacy and new entries."""

    def test_registry_has_toolkit(self):
        from parrot_tools import TOOL_REGISTRY
        assert "file_manager_toolkit" in TOOL_REGISTRY
        assert TOOL_REGISTRY["file_manager_toolkit"] == "parrot.tools.filemanager.FileManagerToolkit"

    def test_registry_has_legacy_tool(self):
        from parrot_tools import TOOL_REGISTRY
        assert "file_manager" in TOOL_REGISTRY
        assert TOOL_REGISTRY["file_manager"] == "parrot.tools.filemanager.FileManagerTool"
