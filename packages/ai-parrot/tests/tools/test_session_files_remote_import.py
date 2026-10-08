"""Tests for importing remote files into the session file store."""

from pathlib import Path
import importlib
import sys

import pytest

from parrot.interfaces.file.session import SessionFileStore
from parrot.tools.session_files import SessionFileToolkit
from parrot.utils.helpers import RequestContext, _current_ctx


@pytest.fixture
def toolkit(tmp_path):
    """Return a session file toolkit backed by a temporary store."""
    return SessionFileToolkit(store=SessionFileStore(root=tmp_path))


@pytest.fixture
def bind():
    """Bind a RequestContext for the duration of a test."""

    def _bind(session_id):
        _current_ctx.set(RequestContext(session_id=session_id))

    yield _bind
    _current_ctx.set(None)


class TestRemoteImport:
    """Remote import behavior with the transport mocked at its boundary."""

    async def test_rejects_unknown_backend(self, toolkit, bind, monkeypatch):
        """Unsupported backends fail before constructing a transport."""
        bind("s1")

        def fail_if_constructed(*args, **kwargs):
            raise AssertionError("FileManagerToolkit must not be constructed")

        monkeypatch.setattr(
            importlib.import_module("parrot.tools.filemanager"),
            "FileManagerToolkit",
            fail_if_constructed,
            raising=False,
        )

        with pytest.raises(ValueError, match="Unsupported backend"):
            await toolkit.import_remote_file("http", "https://example.com/x.docx")

    async def test_import_returns_resolvable_handle(self, toolkit, bind, monkeypatch):
        """A mocked download becomes a handle the store can resolve."""
        bind("s1")
        temp_dirs = []

        class MockFileManagerToolkit:
            """Mock remote transport that writes the requested destination."""

            def __init__(self, manager_type):
                self.manager_type = manager_type

            async def download_file(self, path, destination=None):
                destination_path = Path(destination)
                temp_dirs.append(destination_path.parent)
                destination_path.write_bytes(b"remote document")
                return {"downloaded": True, "destination": str(destination_path), "size": 15}

        monkeypatch.setattr(importlib.import_module("parrot.tools.filemanager"), "FileManagerToolkit", MockFileManagerToolkit)

        result = await toolkit.import_remote_file("temp", "reports/brief.docx")
        record, resolved = await toolkit.store.resolve("s1", result["file_id"])

        assert resolved.read_bytes() == b"remote document"
        assert record.origin == "remote"
        assert result == {"file_id": record.file_id, "filename": "brief.docx", "size": 15}
        assert temp_dirs and not temp_dirs[0].exists()

    async def test_temp_dir_removed_on_failure(self, toolkit, bind, monkeypatch):
        """A download that raises still cleans up its private temporary directory."""
        bind("s1")
        temp_dirs = []

        class FailingFileManagerToolkit:
            """Mock remote transport that fails after capturing its destination."""

            def __init__(self, manager_type):
                self.manager_type = manager_type

            async def download_file(self, path, destination=None):
                temp_dirs.append(Path(destination).parent)
                raise RuntimeError("download failed")

        monkeypatch.setattr(importlib.import_module("parrot.tools.filemanager"), "FileManagerToolkit", FailingFileManagerToolkit)

        with pytest.raises(RuntimeError, match="download failed"):
            await toolkit.import_remote_file("temp", "reports/brief.docx")

        assert temp_dirs and not temp_dirs[0].exists()
