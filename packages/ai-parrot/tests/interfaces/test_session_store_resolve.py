"""Tests for SessionFileStore sandbox resolution."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from parrot.interfaces.file.session import (
    BLOB_SUFFIX,
    MANIFEST_SUFFIX,
    MissingBlob,
    OutsideSandbox,
    SessionFileRecord,
    SessionFileStore,
    UnknownHandle,
)


@pytest.fixture
def store(tmp_path):
    """Return a store rooted in the test directory."""
    return SessionFileStore(root=tmp_path)


def write_manifest(store, session_id: str, file_id: str) -> None:
    """Write a valid manifest sidecar for one test handle."""
    record = SessionFileRecord(
        file_id=file_id,
        session_id=session_id,
        filename="report.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size=4,
        origin="upload",
        created_at=datetime.now(timezone.utc),
    )
    root = store.session_root(session_id)
    (root / f"{file_id}{MANIFEST_SUFFIX}").write_text(record.model_dump_json(), encoding="utf-8")


class TestResolve:
    """Resolution and sandbox-refusal tests."""

    async def test_unknown_handle(self, store):
        """A missing manifest raises UnknownHandle before blob access."""
        with pytest.raises(UnknownHandle):
            await store.resolve("s1", "nope")

    async def test_rejects_traversal_handle(self, store):
        """A traversal handle is rejected before the manifest is read."""
        with pytest.raises(OutsideSandbox):
            await store.resolve("s1", "../../etc/passwd")

    async def test_rejects_absolute_path_handle(self, store):
        """An absolute handle cannot bypass the session root."""
        with pytest.raises(OutsideSandbox):
            await store.resolve("s1", "/etc/passwd")

    async def test_rejects_symlinked_blob(self, store, tmp_path):
        """A manifest whose blob symlinks outside the root is refused."""
        file_id = "linked"
        write_manifest(store, "s1", file_id)
        outside = tmp_path / "outside.bin"
        outside.write_bytes(b"outside")
        (store.session_root("s1") / f"{file_id}{BLOB_SUFFIX}").symlink_to(outside)

        with pytest.raises(OutsideSandbox):
            await store.resolve("s1", file_id)

    async def test_not_resolvable_across_sessions(self, store):
        """A handle valid in s1 raises under s2."""
        file_id = "s1-file"
        write_manifest(store, "s1", file_id)
        (store.session_root("s1") / f"{file_id}{BLOB_SUFFIX}").write_bytes(b"data")

        with pytest.raises(UnknownHandle):
            await store.resolve("s2", file_id)

    async def test_missing_blob(self, store):
        """A manifest present without its blob raises MissingBlob."""
        write_manifest(store, "s1", "missing")

        with pytest.raises(MissingBlob):
            await store.resolve("s1", "missing")

    async def test_resolves_contained_blob(self, store):
        """A valid manifest and regular blob resolve to their canonical path."""
        file_id = "valid"
        write_manifest(store, "s1", file_id)
        blob = store.session_root("s1") / f"{file_id}{BLOB_SUFFIX}"
        blob.write_bytes(b"data")

        record, path = await store.resolve("s1", file_id)

        assert record.file_id == file_id
        assert path == blob.resolve()

    async def test_outside_sandbox_warning_excludes_resolved_path(self, store, caplog):
        """Sandbox refusal logs session and handle but never the resolved path."""
        file_id = "../../sensitive-path"

        with pytest.raises(OutsideSandbox):
            await store.resolve("s1", file_id)

        message = caplog.records[-1].getMessage()
        assert "s1" in message
        assert file_id in message
        assert str(store.session_root("s1")) not in message
