"""Backend-policy and path-validation guards for SessionFileToolkit (FEAT-643)."""

import importlib
from pathlib import Path

import pytest

from parrot.interfaces.file.session import SessionFileStore
from parrot.tools.session_files import REMOTE_BACKENDS, SessionFileToolkit, _validate_remote_path
from parrot.utils.helpers import RequestContext, _current_ctx


@pytest.fixture
def bind():
    """Bind a RequestContext for the duration of a test."""

    def _bind(session_id):
        _current_ctx.set(RequestContext(session_id=session_id))

    yield _bind
    _current_ctx.set(None)


@pytest.fixture
def exploding_transport(monkeypatch):
    """Patch FileManagerToolkit so constructing one fails the test."""

    def _fail(*args, **kwargs):
        raise AssertionError("FileManagerToolkit must not be constructed")

    monkeypatch.setattr(importlib.import_module("parrot.tools.filemanager"), "FileManagerToolkit", _fail)


def _recording_transport(monkeypatch, payload=b"remote document"):
    """Patch FileManagerToolkit with a mock that records its construction kwargs."""
    calls = []

    class RecordingFileManagerToolkit:
        """Mock transport capturing how it was constructed and what it was asked for."""

        def __init__(self, manager_type, **kwargs):
            self.manager_type = manager_type
            self.kwargs = kwargs
            calls.append(self)
            self.paths = []

        async def download_file(self, path, destination=None):
            self.paths.append(path)
            destination_path = Path(destination)
            destination_path.write_bytes(payload)
            return {"downloaded": True, "destination": str(destination_path), "size": len(payload)}

    monkeypatch.setattr(
        importlib.import_module("parrot.tools.filemanager"),
        "FileManagerToolkit",
        RecordingFileManagerToolkit,
    )
    return calls


class TestBackendPolicy:
    """Module 1 — remote by default, local only by operator opt-in."""

    async def test_fs_refused_by_default(self, tmp_path, bind, exploding_transport):
        """AC1 — a default toolkit refuses "fs" without building a transport."""
        toolkit = SessionFileToolkit(store=SessionFileStore(root=tmp_path))
        bind("s1")

        with pytest.raises(ValueError, match="Unsupported backend") as excinfo:
            await toolkit.import_remote_file("fs", "env/.env")

        assert "'fs'" not in str(excinfo.value).split(";", 1)[1]

    @pytest.mark.parametrize("configure_root", [False, True])
    async def test_temp_is_never_supported(self, tmp_path, bind, exploding_transport, configure_root):
        """AC2 — "temp" is in no backend set, under either configuration."""
        root = tmp_path / "importable"
        root.mkdir()
        toolkit = SessionFileToolkit(
            store=SessionFileStore(root=tmp_path / "store"),
            local_import_root=root if configure_root else None,
        )
        bind("s1")

        with pytest.raises(ValueError, match="Unsupported backend"):
            await toolkit.import_remote_file("temp", "reports/brief.docx")

    async def test_local_root_binds_base_path(self, tmp_path, bind, monkeypatch):
        """AC3 — with a root configured, "fs" builds a transport bound to it."""
        root = tmp_path / "importable"
        root.mkdir()
        calls = _recording_transport(monkeypatch)
        toolkit = SessionFileToolkit(store=SessionFileStore(root=tmp_path / "store"), local_import_root=root)
        bind("s1")

        result = await toolkit.import_remote_file("fs", "reports/brief.docx")

        assert calls[0].manager_type == "fs"
        assert calls[0].kwargs == {"base_path": str(root.resolve()), "sandboxed": True}
        record, resolved = await toolkit.store.resolve("s1", result["file_id"])
        assert resolved.read_bytes() == b"remote document"
        assert record.origin == "remote"

    def test_local_root_must_be_a_directory(self, tmp_path):
        """AC4 — a missing or non-directory root fails at construction."""
        missing = tmp_path / "nope"
        a_file = tmp_path / "a.txt"
        a_file.write_text("x")

        for bad in (missing, a_file):
            with pytest.raises(ValueError, match="local_import_root"):
                SessionFileToolkit(store=SessionFileStore(root=tmp_path), local_import_root=bad)

    @pytest.mark.parametrize("backend", sorted(REMOTE_BACKENDS))
    async def test_remote_backend_still_works(self, tmp_path, bind, monkeypatch, backend):
        """AC5 — every remote backend imports unchanged with a valid relative path."""
        calls = _recording_transport(monkeypatch)
        toolkit = SessionFileToolkit(store=SessionFileStore(root=tmp_path))
        bind("s1")

        result = await toolkit.import_remote_file(backend, "reports/brief.docx")

        assert calls[0].manager_type == backend
        assert calls[0].kwargs == {}
        assert calls[0].paths == ["reports/brief.docx"]
        assert result["filename"] == "brief.docx"


class TestRemotePathValidation:
    """Module 2 — the path check runs for every backend, before any I/O."""

    @pytest.mark.parametrize(
        "bad_path",
        [
            "",
            "   ",
            "a\x00b",
            "/etc/passwd",
            "C:\\secrets.txt",
            "\\\\host\\share\\x",
            "../../../etc/passwd",
            "foo/../../bar",
            "foo\\..\\bar",
            "..",
            "./",
        ],
    )
    def test_rejects_bad_remote_path(self, bad_path):
        """AC6 — the pure validator refuses every unsafe form."""
        with pytest.raises(ValueError):
            _validate_remote_path(bad_path)

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("./a/b.docx", "a/b.docx"),
            ("a//b.docx", "a/b.docx"),
            ("a\\b.docx", "a/b.docx"),
            ("a/./b.docx", "a/b.docx"),
            ("brief.docx", "brief.docx"),
        ],
    )
    def test_accepts_normalized_relative_path(self, raw, expected):
        """A safe path comes back normalized to forward slashes."""
        assert _validate_remote_path(raw) == expected

    @pytest.mark.parametrize("bad_path", ["/etc/passwd", "../../../etc/passwd", "foo\\..\\bar"])
    async def test_bad_path_builds_no_transport(self, tmp_path, bind, exploding_transport, bad_path):
        """AC6 — the refusal happens before the transport is constructed."""
        toolkit = SessionFileToolkit(store=SessionFileStore(root=tmp_path))
        bind("s1")

        with pytest.raises(ValueError, match="remote_path"):
            await toolkit.import_remote_file("s3", bad_path)

    async def test_transport_receives_the_normalized_path(self, tmp_path, bind, monkeypatch):
        """The transport never sees a form the validator did not inspect."""
        calls = _recording_transport(monkeypatch)
        toolkit = SessionFileToolkit(store=SessionFileStore(root=tmp_path))
        bind("s1")

        await toolkit.import_remote_file("s3", "./reports//brief.docx")

        assert calls[0].paths == ["reports/brief.docx"]
