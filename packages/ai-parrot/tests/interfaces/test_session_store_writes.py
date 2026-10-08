"""Write-path tests for the session file store."""

import logging
import os

import pytest

from parrot.interfaces.file import session
from parrot.interfaces.file.session import BLOB_SUFFIX, MANIFEST_SUFFIX, SessionFileStore, UnknownHandle


@pytest.fixture
def store(tmp_path):
    """Return a store rooted in the test directory."""
    return SessionFileStore(root=tmp_path)


@pytest.mark.asyncio
class TestWrites:
    """Verify session-file store write and reporting behavior."""

    async def test_put_bytes_creates_blob_and_manifest(self, store):
        """Stored bytes resolve through their manifest record."""
        record = await store.put_bytes("s1", "report.docx", b"PK\x03\x04")

        found, path = await store.resolve("s1", record.file_id)

        assert found.filename == "report.docx"
        assert path.read_bytes() == b"PK\x03\x04"
        assert (store.session_root("s1") / f"{record.file_id}{MANIFEST_SUFFIX}").exists()

    async def test_filename_is_sanitized(self, store):
        """Names are retained only as safe basenames."""
        record = await store.put_bytes("s1", "../../etc/passwd", b"x")

        assert record.filename == "passwd"
        assert "/" not in record.filename

    async def test_duplicate_filenames_get_distinct_handles(self, store):
        """Same names receive distinct handles and blobs."""
        first = await store.put_bytes("s1", "report.docx", b"first")
        second = await store.put_bytes("s1", "report.docx", b"second")

        root = store.session_root("s1")
        assert first.file_id != second.file_id
        assert (root / f"{first.file_id}{BLOB_SUFFIX}").read_bytes() == b"first"
        assert (root / f"{second.file_id}{BLOB_SUFFIX}").read_bytes() == b"second"

    async def test_partial_write_leaves_no_resolvable_handle(self, store, monkeypatch):
        """A manifest rename failure leaves no usable handle or blob."""
        original_replace = os.replace

        def fail_manifest_replace(source, destination):
            """Fail only while placing the manifest sidecar."""
            if str(destination).endswith(MANIFEST_SUFFIX):
                raise OSError("simulated manifest failure")
            return original_replace(source, destination)

        monkeypatch.setattr(session.os, "replace", fail_manifest_replace)
        monkeypatch.setattr(session, "_new_handle", lambda: "failed-handle")

        with pytest.raises(OSError, match="simulated manifest failure"):
            await store.put_bytes("s1", "report.docx", b"content")

        root = store.session_root("s1")
        assert not (root / f"failed-handle{BLOB_SUFFIX}").exists()
        with pytest.raises(UnknownHandle):
            await store.resolve("s1", "failed-handle")

    async def test_list_files_newest_first_and_skips_unparseable_manifest(self, store):
        """Manifest records are sorted without trusting invalid sidecars."""
        first = await store.put_bytes("s1", "first.txt", b"first")
        second = await store.put_bytes("s1", "second.txt", b"second")
        (store.session_root("s1") / f"broken{MANIFEST_SUFFIX}").write_text("not json", encoding="utf-8")

        records = await store.list_files("s1")

        assert [record.file_id for record in records] == [second.file_id, first.file_id]
        assert await store.usage_bytes("s1") == len(b"firstsecond")

    async def test_store_survives_restart(self, store, tmp_path):
        """A new store over the root resolves an existing handle."""
        record = await store.put_bytes("s1", "report.docx", b"content")

        found, path = await SessionFileStore(root=tmp_path).resolve("s1", record.file_id)

        assert found == record
        assert path.read_bytes() == b"content"

    async def test_warn_threshold_logs_and_still_stores(self, store, monkeypatch, caplog):
        """Crossing the advisory threshold warns but never rejects the upload."""
        monkeypatch.setattr(session, "SESSION_FILES_WARN_BYTES", 1)
        caplog.set_level(logging.WARNING, logger=session.__name__)

        record = await store.put_bytes("s1", "report.docx", b"content")

        assert record.size == len(b"content")
        assert any("warning threshold" in item.getMessage() for item in caplog.records)
