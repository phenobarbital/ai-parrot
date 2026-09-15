"""Bounded immutable artifact blob I/O (FEAT-538 / TASK-2996).

Three required cases from the task's Test Specification:

- ``test_roundtrip`` — frame, text and JSON fingerprints survive the blob
  round trip, including schema and index metadata.
- ``test_bounded_page`` — a small page read never fully materializes an
  oversized table, and both the encoded and decoded byte ceilings hold.
- ``test_failed_publish`` — a failed upload, stat or checksum yields no
  publishable reference, with no pickle and no oversized inline fallback.

The page test uses an **armed trap** rather than an observation: it
replaces ``ParquetFile.read`` with a function that raises. Asserting only
that a page has the right number of rows would pass just as happily
against an implementation that decoded the whole table and then sliced
it — which is precisely the behaviour the requirement forbids.

Happy paths run against a real ``LocalFileManager`` over ``tmp_path``.
Failure paths use narrow stubs that fail one specific operation, because
the point is the adapter's reaction to a failing store, not the store.
"""

from __future__ import annotations

import ast
import io
import pathlib
from typing import Any, Optional

import numpy as np
import pandas as pd
import pytest
from parrot.interfaces.artifact_store import PayloadRefusal
from parrot.tools.working_memory.task_memory.blob import (
    BLOB_CORRUPTED,
    ArtifactBlobStore,
    BlobFormat,
    BlobImmutabilityError,
    BlobPublishError,
    BlobRef,
    UnsupportedBlobPayload,
)
from parrot.tools.working_memory.task_memory.models import ArtifactKind, EvidenceRef, LimitExceeded, TaskScope
from parrot.tools.working_memory.task_memory.snapshots import (
    CHECKSUM_PREFIX,
    FINGERPRINT_PREFIX,
    blob_checksum,
    canonical_json_bytes,
    fingerprint_bytes,
    fingerprint_dataframe,
)

# The repo-wide ``tests/conftest.py`` installs an ``AsyncMock``-backed stub
# for ``parrot.interfaces.file`` so unrelated suites can collect without
# navigator-api's file managers. Importing ``LocalFileManager`` through that
# shim here would yield a mock whose ``exists()`` is truthy, silently turning
# every I/O assertion below into a no-op. The real implementation survives at
# ``navigator.utils.file`` (the conftest guards those attrs with ``hasattr``),
# so this module imports it directly and refuses to run against a stub.
from navigator.utils.file import LocalFileManager  # noqa: E402  isort:skip

_REAL_FILE_MANAGER = LocalFileManager.__module__.startswith("navigator.")

pytestmark = pytest.mark.skipif(
    not _REAL_FILE_MANAGER,
    reason=(
        "navigator-api's real LocalFileManager is unavailable; only the conftest "
        "AsyncMock stub is installed. This is an ENVIRONMENTAL SKIP, not a pass — "
        "blob I/O was not exercised against a real filesystem."
    ),
)

SCOPE = TaskScope(chatbot_id="bot-a", user_id="user-1", session_id="sess-1")
OTHER_SCOPE = TaskScope(chatbot_id="bot-a", user_id="user-2", session_id="sess-1")


@pytest.fixture()
def store(tmp_path: pathlib.Path) -> ArtifactBlobStore:
    """Return a blob store over a real sandboxed local file manager.

    Args:
        tmp_path: pytest's per-test directory.

    Returns:
        The store under test.
    """
    manager = LocalFileManager(base_path=str(tmp_path), create_base=True, sandboxed=True)
    return ArtifactBlobStore(manager)


def ref(artifact_id: str = "art-1", version: int = 1) -> EvidenceRef:
    """Build an evidence reference.

    Args:
        artifact_id: Artifact identity.
        version: Version number.

    Returns:
        The reference.
    """
    return EvidenceRef(artifact_id=artifact_id, version=version)


def frame(rows: int = 100) -> pd.DataFrame:
    """Build a deterministic numeric/string frame with a named index.

    Args:
        rows: Row count.

    Returns:
        The frame.
    """
    return pd.DataFrame(
        {
            "i": range(rows),
            "f": np.arange(rows, dtype=float) / 3,
            "s": [f"row-{n}" for n in range(rows)],
        },
        index=pd.Index([f"r{n}" for n in range(rows)], name="rid"),
    )


# ─────────────────────────────────────────────────────────────
# Stubs for failure injection
# ─────────────────────────────────────────────────────────────


class _StubManager:
    """A file manager whose individual operations can be made to fail."""

    def __init__(
        self,
        *,
        fail_write: bool = False,
        decline_write: bool = False,
        fail_stat: bool = False,
        wrong_size: bool = False,
        corrupt_on_read: bool = False,
        fail_delete: bool = False,
    ) -> None:
        """Initialize the stub.

        Args:
            fail_write: ``create_from_bytes`` raises.
            decline_write: ``create_from_bytes`` returns ``False``.
            fail_stat: ``get_file_metadata`` raises.
            wrong_size: ``get_file_metadata`` reports a mismatched size.
            corrupt_on_read: reads return altered bytes.
            fail_delete: ``delete_file`` raises.
        """
        self.objects: dict = {}
        self.fail_write = fail_write
        self.decline_write = decline_write
        self.fail_stat = fail_stat
        self.wrong_size = wrong_size
        self.corrupt_on_read = corrupt_on_read
        self.fail_delete = fail_delete
        self.deleted: list = []

    async def create_from_bytes(self, path: str, data: Any) -> bool:
        """Store bytes, or fail as configured."""
        if self.fail_write:
            raise OSError("disk on fire")
        if self.decline_write:
            return False
        self.objects[path] = bytes(data)
        return True

    async def exists(self, path: str) -> bool:
        """Whether an object is present."""
        return path in self.objects

    async def get_file_metadata(self, path: str) -> Any:
        """Report an object's metadata, or fail as configured."""
        if self.fail_stat:
            raise OSError("stat failed")
        if path not in self.objects:
            raise FileNotFoundError(path)
        size = len(self.objects[path]) + (7 if self.wrong_size else 0)

        class _Metadata:
            def __init__(self, size: int) -> None:
                self.size = size
                self.name = path

        return _Metadata(size)

    async def download_file(self, source: str, destination: Any) -> pathlib.Path:
        """Copy an object into ``destination``, corrupting it if configured."""
        if source not in self.objects:
            raise FileNotFoundError(source)
        payload = self.objects[source]
        if self.corrupt_on_read:
            payload = payload[:-1] + bytes([(payload[-1] + 1) % 256]) if payload else b"x"
        destination.write(payload)
        return pathlib.Path(source)

    async def delete_file(self, path: str) -> bool:
        """Remove an object, or fail as configured."""
        if self.fail_delete:
            raise OSError("cannot delete")
        self.deleted.append(path)
        return self.objects.pop(path, None) is not None


# ─────────────────────────────────────────────────────────────
# test_roundtrip
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_roundtrip_dataframe_preserves_fingerprint(store: ArtifactBlobStore) -> None:
    """A frame's content fingerprint survives the Parquet round trip."""
    df = frame(200)
    reference = ref()
    blob = await store.publish(SCOPE, reference, df)

    assert blob.blob_format is BlobFormat.PARQUET
    assert blob.kind is ArtifactKind.DATAFRAME
    assert blob.row_count == 200
    assert blob.content_fingerprint == fingerprint_dataframe(df)
    assert blob.content_fingerprint.startswith(FINGERPRINT_PREFIX)
    assert blob.checksum.startswith(CHECKSUM_PREFIX)

    result = await store.load(SCOPE, reference, blob, max_bytes=50_000_000)
    assert result.ok
    pd.testing.assert_frame_equal(result.payload, df)
    assert fingerprint_dataframe(result.payload) == blob.content_fingerprint


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "df,label",
    [
        (pd.DataFrame({"a": [1, 2, 3], "b": [1.5, 2.5, 3.5]}), "numeric"),
        (pd.DataFrame({"v": [1, 2]}, index=pd.Index(["x", "y"], name="rid")), "named-index"),
        (pd.DataFrame({"t": pd.to_datetime(["2026-01-01", "2026-01-02"]), "b": [True, False]}), "datetime-bool"),
        (pd.DataFrame({"c": pd.Categorical(["a", "b", "a"])}), "categorical"),
        (pd.DataFrame({"n": [1.0, None, 3.0]}), "nulls"),
        (
            pd.DataFrame(
                {"a": [1, 2]},
                index=pd.MultiIndex.from_tuples([("x", 1), ("y", 2)], names=["k", "i"]),
            ),
            "multiindex",
        ),
    ],
    ids=lambda v: v if isinstance(v, str) else "",
)
async def test_roundtrip_preserves_schema_and_index_metadata(
    store: ArtifactBlobStore, df: pd.DataFrame, label: str
) -> None:
    """Schema and index metadata survive, so the fingerprint still matches.

    The fingerprint folds in shape, ordered column names, dtypes, index
    names and index dtype, so an equal fingerprint after the round trip
    *is* the assertion that this metadata survived.
    """
    reference = ref(f"art-{label}")
    blob = await store.publish(SCOPE, reference, df)
    result = await store.load(SCOPE, reference, blob, max_bytes=50_000_000)

    assert result.ok
    assert fingerprint_dataframe(result.payload) == fingerprint_dataframe(df)
    assert list(result.payload.dtypes) == list(df.dtypes)
    assert result.payload.index.names == df.index.names
    pd.testing.assert_frame_equal(result.payload, df)


@pytest.mark.asyncio
async def test_roundtrip_json_and_text(store: ArtifactBlobStore) -> None:
    """JSON and text round-trip through canonical bytes with stable fingerprints."""
    payload = {"b": 2, "a": [1, 2, {"z": None}], "u": "ünïcode ✓"}
    json_ref = ref("art-json")
    json_blob = await store.publish(SCOPE, json_ref, payload)
    assert json_blob.blob_format is BlobFormat.JSON
    assert json_blob.kind is ArtifactKind.JSON
    assert json_blob.content_fingerprint == fingerprint_bytes(canonical_json_bytes(payload))

    json_result = await store.load(SCOPE, json_ref, json_blob, max_bytes=100_000)
    assert json_result.ok and json_result.payload == payload

    text = "héllo ✓\nsecond line"
    text_ref = ref("art-text")
    text_blob = await store.publish(SCOPE, text_ref, text)
    assert text_blob.blob_format is BlobFormat.TEXT
    assert text_blob.content_fingerprint == fingerprint_bytes(text.encode("utf-8"))

    text_result = await store.load(SCOPE, text_ref, text_blob, max_bytes=100_000)
    assert text_result.ok and text_result.payload == text


@pytest.mark.asyncio
async def test_roundtrip_checksum_is_not_the_content_fingerprint(store: ArtifactBlobStore) -> None:
    """The two digests answer different questions and must not be conflated.

    Parquet encoding is not byte-stable across writes, so the same frame
    can land with different checksums while its content fingerprint is
    unchanged. The distinct prefixes exist so the two can never be
    silently compared.
    """
    df = frame(50)
    blob = await store.publish(SCOPE, ref("art-a"), df)

    assert blob.checksum != blob.content_fingerprint
    assert blob.checksum.startswith(CHECKSUM_PREFIX)
    assert blob.content_fingerprint.startswith(FINGERPRINT_PREFIX)
    assert blob.checksum == blob_checksum(await store._download(blob.key))


@pytest.mark.asyncio
async def test_roundtrip_keys_are_scoped_and_immutable(store: ArtifactBlobStore) -> None:
    """Keys separate scopes and versions, and cannot escape their subtree."""
    reference = ref("art-1", 1)
    mine = store.blob_key(SCOPE, reference, BlobFormat.PARQUET)
    theirs = store.blob_key(OTHER_SCOPE, reference, BlobFormat.PARQUET)
    next_version = store.blob_key(SCOPE, ref("art-1", 2), BlobFormat.PARQUET)

    assert mine != theirs, "two scopes must never share a key"
    assert mine != next_version, "two versions must never share a key"
    assert mine.endswith("/v1.parquet")

    # A component containing separators or traversal is encoded, not obeyed.
    # The property that matters is per-SEGMENT: no segment may *be* "." or
    # ".."; a segment merely *containing* dots (e.g. "..%2F..%2Fetc") is an
    # ordinary directory name and is harmless.
    for hostile in (
        TaskScope(chatbot_id="../../etc", user_id="a/b", session_id="s"),
        TaskScope(chatbot_id="..", user_id="..", session_id=".."),
        TaskScope(chatbot_id=".", user_id="x", session_id="y"),
    ):
        key = store.blob_key(hostile, reference, BlobFormat.PARQUET)
        segments = key.split("/")
        assert ".." not in segments, f"traversal segment in {key!r}"
        assert "." not in segments, f"current-dir segment in {key!r}"
        assert key.count("/") == mine.count("/"), "an encoded component adds no path depth"

    # Encoding stays injective, so distinct scopes cannot collide.
    a = store.blob_key(TaskScope(chatbot_id="a/b", user_id="u", session_id="s"), reference, BlobFormat.PARQUET)
    b = store.blob_key(TaskScope(chatbot_id="a", user_id="b/u", session_id="s"), reference, BlobFormat.PARQUET)
    assert a != b


@pytest.mark.asyncio
async def test_roundtrip_republish_is_idempotent_but_immutable(store: ArtifactBlobStore) -> None:
    """A byte-identical retry succeeds; changed content for a version does not."""
    df = frame(20)
    reference = ref()
    first = await store.publish(SCOPE, reference, df)
    again = await store.publish(SCOPE, reference, df)
    assert again.key == first.key
    assert again.content_fingerprint == first.content_fingerprint

    with pytest.raises(BlobImmutabilityError, match="immutable"):
        await store.publish(SCOPE, reference, frame(21))

    # The original bytes are untouched.
    result = await store.load(SCOPE, reference, first, max_bytes=50_000_000)
    assert result.ok and len(result.payload) == 20


@pytest.mark.asyncio
async def test_roundtrip_delete_and_archive(store: ArtifactBlobStore, tmp_path: pathlib.Path) -> None:
    """Archive verifies before returning; delete is idempotent."""
    reference = ref()
    blob = await store.publish(SCOPE, reference, frame(30))

    archived = await store.archive(SCOPE, blob, "archive/task-1/v1.parquet")
    assert archived.key == "archive/task-1/v1.parquet"
    assert archived.checksum == blob.checksum
    assert await store.exists(archived)

    assert await store.delete(SCOPE, blob) is True
    assert await store.exists(blob) is False
    # Retention retries must be idempotent.
    assert await store.delete(SCOPE, blob) is False

    # The archived copy survives the source's deletion.
    assert await store.exists(archived)


@pytest.mark.asyncio
async def test_roundtrip() -> None:
    """Required aggregate case: fingerprints survive the blob round trip."""
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        blobs = ArtifactBlobStore(LocalFileManager(base_path=directory, create_base=True, sandboxed=True))
        df = frame(75)
        reference = ref("agg-df")
        blob = await blobs.publish(SCOPE, reference, df)
        result = await blobs.load(SCOPE, reference, blob, max_bytes=50_000_000)
        assert result.ok
        assert fingerprint_dataframe(result.payload) == fingerprint_dataframe(df)
        assert result.payload.index.name == "rid"


# ─────────────────────────────────────────────────────────────
# test_bounded_page
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bounded_page_never_materializes_the_whole_table(
    store: ArtifactBlobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A page read must not decode every row.

    Armed trap: ``ParquetFile.read`` is replaced with a function that
    raises. An implementation that read the whole table and sliced it
    afterwards would produce a correct-looking page, so counting rows
    alone would not detect it.
    """
    import pyarrow.parquet as pq

    reference = ref("art-big")
    blob = await store.publish(SCOPE, reference, frame(20_000))

    def _forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a bounded page read must not call ParquetFile.read()")

    monkeypatch.setattr(pq.ParquetFile, "read", _forbidden)
    monkeypatch.setattr(pq, "read_table", _forbidden)

    result = await store.load(SCOPE, reference, blob, max_bytes=5_000_000, offset=10, limit=5)

    assert result.ok
    assert len(result.payload) == 5
    assert result.total_rows == 20_000
    assert result.truncated is True
    assert result.offset == 10 and result.limit == 5
    assert list(result.payload.index) == [f"r{n}" for n in range(10, 15)]

    # The trap really is armed — a FULL read must now fail.
    with pytest.raises(AssertionError, match="must not call"):
        await store.load(SCOPE, reference, blob, max_bytes=5_000_000)


@pytest.mark.asyncio
async def test_bounded_page_windows_are_correct(store: ArtifactBlobStore) -> None:
    """Pages return exactly the requested window, including at the tail."""
    df = frame(1_000)
    reference = ref("art-pages")
    blob = await store.publish(SCOPE, reference, df)

    for offset, limit, expected in ((0, 10, 10), (500, 25, 25), (995, 10, 5), (1_000, 10, 0)):
        result = await store.load(SCOPE, reference, blob, max_bytes=5_000_000, offset=offset, limit=limit)
        assert result.ok, (offset, limit)
        assert len(result.payload) == expected, (offset, limit)
        if expected:
            pd.testing.assert_frame_equal(result.payload, df.iloc[offset : offset + expected])


@pytest.mark.asyncio
async def test_bounded_page_decoded_ceiling_holds(store: ArtifactBlobStore) -> None:
    """An over-ceiling page is refused and carries no payload."""
    reference = ref("art-wide")
    blob = await store.publish(SCOPE, reference, frame(5_000))

    refused = await store.load(SCOPE, reference, blob, max_bytes=10, offset=0, limit=1_000)
    assert not refused.ok
    assert refused.payload is None, "a refusal must never carry data"
    assert refused.refusal == PayloadRefusal.TOO_LARGE
    assert refused.guidance

    # A smaller page of the same table still succeeds.
    ok = await store.load(SCOPE, reference, blob, max_bytes=5_000_000, offset=0, limit=3)
    assert ok.ok and len(ok.payload) == 3


@pytest.mark.asyncio
async def test_bounded_page_encoded_ceiling_refuses_before_downloading(tmp_path: pathlib.Path) -> None:
    """An oversized object is refused on its stat, before any transfer.

    The pinned interface has no byte-range read, so the size pre-check is
    the only bound available on the transfer. If it did not run first,
    the whole object would already be in memory by the time anyone
    noticed.
    """
    manager = _StubManager()
    blobs = ArtifactBlobStore(manager, max_encoded_bytes=10_000_000)
    reference = ref("art-enc")
    blob = await blobs.publish(SCOPE, reference, frame(500))

    downloads: list = []
    original = manager.download_file

    async def _counting(source: str, destination: Any) -> Any:
        downloads.append(source)
        return await original(source, destination)

    manager.download_file = _counting  # type: ignore[method-assign]
    tiny = ArtifactBlobStore(manager, max_encoded_bytes=16)

    refused = await tiny.load(SCOPE, reference, blob, max_bytes=50_000_000)
    assert not refused.ok
    assert refused.refusal == PayloadRefusal.TOO_LARGE
    assert refused.payload is None
    assert downloads == [], "the object must not be transferred before being refused"


@pytest.mark.asyncio
async def test_bounded_page_zero_max_bytes_never_rehydrates(store: ArtifactBlobStore) -> None:
    """``max_bytes=0`` means never, and no request reopens it."""
    reference = ref()
    blob = await store.publish(SCOPE, reference, frame(10))

    for kwargs in ({}, {"offset": 0, "limit": 1}):
        result = await store.load(SCOPE, reference, blob, max_bytes=0, **kwargs)
        assert not result.ok and result.payload is None


@pytest.mark.asyncio
async def test_bounded_page_rejects_nonsense_bounds(store: ArtifactBlobStore) -> None:
    """Invalid bounds raise rather than being silently clamped."""
    reference = ref()
    blob = await store.publish(SCOPE, reference, frame(10))

    with pytest.raises(ValueError, match="max_bytes"):
        await store.load(SCOPE, reference, blob, max_bytes=-1)
    with pytest.raises(ValueError, match="offset"):
        await store.load(SCOPE, reference, blob, max_bytes=1000, offset=-1)
    with pytest.raises(ValueError, match="limit"):
        await store.load(SCOPE, reference, blob, max_bytes=1000, limit=0)


@pytest.mark.asyncio
async def test_bounded_page_non_tabular_cannot_be_paged(store: ArtifactBlobStore) -> None:
    """Text and JSON have no rows, so a page request is refused explicitly."""
    reference = ref("art-text")
    blob = await store.publish(SCOPE, reference, "some text")

    result = await store.load(SCOPE, reference, blob, max_bytes=10_000, offset=0, limit=5)
    assert not result.ok
    assert result.refusal == PayloadRefusal.UNSUPPORTED
    assert result.payload is None


@pytest.mark.asyncio
async def test_bounded_page() -> None:
    """Required aggregate case: bounded pages and byte ceilings hold."""
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        blobs = ArtifactBlobStore(LocalFileManager(base_path=directory, create_base=True, sandboxed=True))
        reference = ref("agg-page")
        blob = await blobs.publish(SCOPE, reference, frame(5_000))

        page = await blobs.load(SCOPE, reference, blob, max_bytes=5_000_000, offset=100, limit=4)
        assert page.ok and len(page.payload) == 4 and page.total_rows == 5_000

        refused = await blobs.load(SCOPE, reference, blob, max_bytes=8, offset=0, limit=500)
        assert not refused.ok and refused.payload is None


# ─────────────────────────────────────────────────────────────
# test_failed_publish
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_failed_publish_write_failure_yields_no_reference() -> None:
    """A write that raises produces no reference at all."""
    manager = _StubManager(fail_write=True)
    blobs = ArtifactBlobStore(manager)

    with pytest.raises(BlobPublishError, match="failed to write"):
        await blobs.publish(SCOPE, ref(), frame(10))
    assert manager.objects == {}


@pytest.mark.asyncio
async def test_failed_publish_declined_write_yields_no_reference() -> None:
    """A file manager returning ``False`` is a failure, not a success."""
    blobs = ArtifactBlobStore(_StubManager(decline_write=True))
    with pytest.raises(BlobPublishError, match="declined"):
        await blobs.publish(SCOPE, ref(), frame(10))


@pytest.mark.asyncio
async def test_failed_publish_stat_failure_removes_the_partial_object() -> None:
    """A blob that cannot be stat'd is not publishable, and is cleaned up."""
    manager = _StubManager(fail_stat=True)
    blobs = ArtifactBlobStore(manager)

    with pytest.raises(BlobPublishError, match="stat"):
        await blobs.publish(SCOPE, ref(), frame(10))

    assert manager.objects == {}, "the unverified object must not be left as a phantom target"
    assert manager.deleted, "cleanup was attempted"


@pytest.mark.asyncio
async def test_failed_publish_size_mismatch_is_rejected() -> None:
    """A stored size that disagrees with what was sent fails verification."""
    manager = _StubManager(wrong_size=True)
    blobs = ArtifactBlobStore(manager)

    with pytest.raises(BlobPublishError, match="stored .* bytes, expected"):
        await blobs.publish(SCOPE, ref(), frame(10))
    assert manager.objects == {}


@pytest.mark.asyncio
async def test_failed_publish_checksum_mismatch_is_rejected() -> None:
    """Bytes that come back altered fail verification, so nothing is published."""
    manager = _StubManager(corrupt_on_read=True)
    blobs = ArtifactBlobStore(manager)

    with pytest.raises(BlobPublishError, match="checksum"):
        await blobs.publish(SCOPE, ref(), frame(10))
    assert manager.objects == {}


@pytest.mark.asyncio
async def test_failed_publish_cleanup_failure_does_not_mask_the_real_error() -> None:
    """A failed cleanup must not replace the publish failure.

    An orphan blob is expected after a crash and is swept later; losing
    the reason the publish failed is not recoverable.
    """
    manager = _StubManager(corrupt_on_read=True, fail_delete=True)
    blobs = ArtifactBlobStore(manager)

    with pytest.raises(BlobPublishError, match="checksum"):
        await blobs.publish(SCOPE, ref(), frame(10))


@pytest.mark.asyncio
async def test_failed_publish_rejects_unsupported_payloads(store: ArtifactBlobStore) -> None:
    """Binary and arbitrary objects are refused — there is no pickle path."""

    class _Opaque:
        pass

    for value, label in ((b"raw bytes", "bytes"), (_Opaque(), "object"), ({1, 2}, "set")):
        with pytest.raises(UnsupportedBlobPayload):
            await store.publish(SCOPE, ref(f"art-{label}"), value)


@pytest.mark.asyncio
async def test_failed_publish_rejects_nested_mutable_frames(store: ArtifactBlobStore) -> None:
    """A frame whose cells are mutable objects cannot be durable evidence.

    Phase 0 measured why: ``copy(deep=True)`` does not detach such cells
    and pandas hashes them by ``repr``, so no fingerprint over the frame
    proves content integrity. Storing it would create bytes that look
    authoritative and prove nothing.
    """
    nested = pd.DataFrame({"v": [1.0, 2.0], "obj": pd.Series([{"a": 1}, {"b": 2}], dtype="object")})

    with pytest.raises(UnsupportedBlobPayload, match="mutable or non-canonical"):
        await store.publish(SCOPE, ref("art-nested"), nested)


@pytest.mark.asyncio
async def test_failed_publish_declared_kind_must_match(store: ArtifactBlobStore) -> None:
    """A declared kind that lies about the value is refused, not trusted."""
    with pytest.raises(UnsupportedBlobPayload, match="does not match"):
        await store.publish(SCOPE, ref(), "text", kind=ArtifactKind.DATAFRAME)


@pytest.mark.asyncio
async def test_failed_publish_oversized_payload_is_refused_not_inlined() -> None:
    """An over-ceiling payload raises; it is never silently stored inline.

    ``OverflowStore`` falls back to inline data when a write fails. That
    is fine for a JSON definition and wrong for durable evidence, so this
    adapter has no such path.
    """
    manager = _StubManager()
    blobs = ArtifactBlobStore(manager, max_encoded_bytes=256)

    with pytest.raises(LimitExceeded) as excinfo:
        await blobs.publish(SCOPE, ref(), frame(5_000))

    assert excinfo.value.field == "encoded blob"
    assert manager.objects == {}, "an over-ceiling payload must not be written anywhere"


@pytest.mark.asyncio
async def test_failed_publish_load_reports_missing_and_corrupt_honestly() -> None:
    """A vanished or altered blob is reported, never silently substituted."""
    manager = _StubManager()
    blobs = ArtifactBlobStore(manager)
    reference = ref()
    blob = await blobs.publish(SCOPE, reference, frame(10))

    manager.objects.pop(blob.key)
    missing = await blobs.load(SCOPE, reference, blob, max_bytes=5_000_000)
    assert not missing.ok and missing.refusal == PayloadRefusal.MISSING and missing.payload is None

    corrupting = _StubManager()
    corrupting.objects[blob.key] = b"not a parquet file at all"
    tampered = ArtifactBlobStore(corrupting)
    result = await tampered.load(SCOPE, reference, blob, max_bytes=5_000_000)
    assert not result.ok
    assert result.refusal == BLOB_CORRUPTED
    assert result.payload is None


@pytest.mark.asyncio
async def test_failed_publish_archive_must_verify_before_returning() -> None:
    """An unverifiable archive raises, so it cannot authorize a deletion."""
    manager = _StubManager()
    blobs = ArtifactBlobStore(manager)
    blob = await blobs.publish(SCOPE, ref(), frame(10))

    manager.corrupt_on_read = True
    with pytest.raises(BlobPublishError):
        await blobs.archive(SCOPE, blob, "archive/x.parquet")


def test_failed_publish_module_imports_no_pickle() -> None:
    """The adapter must have no pickle path at all.

    Checked structurally: a runtime test can only prove pickle was not
    reached on the paths it exercised, whereas an AST check proves the
    module never imports it.
    """
    import parrot.tools.working_memory.task_memory.blob as module

    tree = ast.parse(pathlib.Path(module.__file__).read_text(encoding="utf-8"))
    imported: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert "pickle" not in imported
    assert "cloudpickle" not in imported
    assert "parrot" in imported  # sanity: the walk really inspected imports


@pytest.mark.asyncio
async def test_failed_publish() -> None:
    """Required aggregate case: a failed publish yields no reference."""
    for manager in (
        _StubManager(fail_write=True),
        _StubManager(decline_write=True),
        _StubManager(fail_stat=True),
        _StubManager(wrong_size=True),
        _StubManager(corrupt_on_read=True),
    ):
        blobs = ArtifactBlobStore(manager)
        with pytest.raises(BlobPublishError):
            await blobs.publish(SCOPE, ref(), frame(10))
        assert manager.objects == {}

    test_failed_publish_module_imports_no_pickle()


# ─────────────────────────────────────────────────────────────
# Model surface
# ─────────────────────────────────────────────────────────────


def test_blob_ref_is_frozen_and_strict() -> None:
    """A verified reference cannot be edited after the fact."""
    from pydantic import ValidationError

    blob = BlobRef(
        key="k",
        blob_format=BlobFormat.JSON,
        checksum="ck_0123456789abcdef",
        byte_size=10,
    )
    with pytest.raises(ValidationError):
        blob.key = "other"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        BlobRef(key="k", blob_format=BlobFormat.JSON, checksum="c", byte_size=1, surprise=1)  # type: ignore[call-arg]


def test_blob_format_extensions_are_distinct() -> None:
    """Each format has its own extension, so keys cannot collide by type."""
    extensions = {fmt: fmt.extension for fmt in BlobFormat}
    assert len(set(extensions.values())) == len(extensions)
    assert BlobFormat.PARQUET.is_tabular is True
    assert BlobFormat.JSON.is_tabular is False
    assert BlobFormat.TEXT.is_tabular is False


def test_store_rejects_nonsense_configuration(tmp_path: pathlib.Path) -> None:
    """A non-positive transfer ceiling is a caller bug."""
    manager = LocalFileManager(base_path=str(tmp_path), create_base=True, sandboxed=True)
    for bad in (0, -1):
        with pytest.raises(ValueError, match="max_encoded_bytes"):
            ArtifactBlobStore(manager, max_encoded_bytes=bad)
