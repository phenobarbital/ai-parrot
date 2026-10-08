"""Backend-policy and path-validation guards for SessionFileToolkit (FEAT-643)."""

import importlib
from pathlib import Path

import pytest

from parrot.interfaces.file.session import SessionFileStore
from parrot.tools.session_files import (
    DEFAULT_MAX_FILE_BYTES,
    REMOTE_BACKENDS,
    FileTooLarge,
    SessionFileToolkit,
    _validate_remote_path,
)
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
            self.destinations = []

        async def download_file(self, path, destination=None):
            self.paths.append(path)
            self.destinations.append(destination)
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


class TestByteCap:
    """Module 3 — neither write path may exceed the per-file cap."""

    def test_rejects_non_positive_cap(self, tmp_path):
        """AC9 — a zero or negative cap is a wiring error, caught at construction."""
        for bad in (0, -1):
            with pytest.raises(ValueError, match="max_file_bytes"):
                SessionFileToolkit(store=SessionFileStore(root=tmp_path), max_file_bytes=bad)

    def test_default_cap_exceeds_jira_limit(self):
        """The default leaves Jira-legal attachments (10 MB) comfortably inside."""
        assert DEFAULT_MAX_FILE_BYTES > 10 * 1024 * 1024

    async def test_generated_file_over_cap(self, tmp_path, bind):
        """AC7 — oversized generated text is refused and nothing is stored."""
        toolkit = SessionFileToolkit(store=SessionFileStore(root=tmp_path), max_file_bytes=16)
        bind("s1")

        with pytest.raises(FileTooLarge) as excinfo:
            await toolkit.store_generated_file("report.md", "x" * 17)

        assert excinfo.value.code == "file_too_large"
        assert await toolkit.list_session_files() == {"files": []}

    async def test_generated_cap_measures_encoded_bytes(self, tmp_path, bind):
        """The cap counts UTF-8 bytes, not characters."""
        toolkit = SessionFileToolkit(store=SessionFileStore(root=tmp_path), max_file_bytes=4)
        bind("s1")

        with pytest.raises(FileTooLarge):
            await toolkit.store_generated_file("report.md", "\u00e1\u00e9\u00ed")  # 3 chars, 6 bytes

    async def test_import_over_cap_not_read_into_memory(self, tmp_path, bind, monkeypatch):
        """AC8 — the cap is enforced on stat(), before the bytes are read."""
        temp_dirs = _recording_transport(monkeypatch, payload=b"y" * 64)
        toolkit = SessionFileToolkit(store=SessionFileStore(root=tmp_path), max_file_bytes=16)
        bind("s1")

        def _fail_read(self, *args, **kwargs):
            raise AssertionError("the download must not be read into memory when over the cap")

        monkeypatch.setattr(Path, "read_bytes", _fail_read)

        with pytest.raises(FileTooLarge):
            await toolkit.import_remote_file("s3", "reports/brief.docx")

        assert await toolkit.list_session_files() == {"files": []}
        # The transport's destination lived in a private temp dir removed by the finally.
        assert not Path(temp_dirs[0].destinations[0]).parent.exists()

    async def test_import_at_cap_succeeds(self, tmp_path, bind, monkeypatch):
        """The boundary is inclusive: exactly max_file_bytes is stored."""
        _recording_transport(monkeypatch, payload=b"z" * 16)
        toolkit = SessionFileToolkit(store=SessionFileStore(root=tmp_path), max_file_bytes=16)
        bind("s1")

        result = await toolkit.import_remote_file("s3", "reports/brief.docx")

        assert result["size"] == 16
