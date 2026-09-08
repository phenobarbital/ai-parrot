"""Bounded, immutable artifact blob I/O (FEAT-538, Delivery B).

Implements the durable half of §2 *Catalog Backend, Versions, and
Evidence*: a supported payload that cannot stay in RAM is written once,
verified, and only then referenced.

Three rules shape everything here.

**Never publish a reference before its bytes exist.** :meth:`ArtifactBlobStore.
publish` writes, re-reads and checksum-verifies the blob *before* returning
a :class:`BlobRef`. Any failure raises and yields no reference at all. An
orphan blob left behind by a crash is expected and is swept later; a
*phantom reference* — an index row pointing at bytes that were never
written — is unrecoverable, so the ordering is not negotiable.

**Blobs are immutable.** A version's bytes are written exactly once.
The underlying file manager happily overwrites (verified: a second
``create_from_bytes`` to the same path succeeds and changes the size), so
immutability is enforced *here* rather than assumed of storage. A
re-publish of byte-identical content is accepted as an idempotent retry;
a re-publish of *different* content raises.

**A blob checksum is not a content fingerprint.** They answer different
questions and must never be compared. Parquet encoding is not
deterministic across writes, so the same frame yields a different
checksum each time while its content fingerprint is stable.
:mod:`~parrot.tools.working_memory.task_memory.snapshots` already provides
both with deliberately distinct prefixes (``ck_`` vs ``fp_``) and this
module reuses them rather than hashing anything itself.

Supported formats are Parquet for DataFrames and canonical UTF-8 bytes
for JSON and text. Binary and arbitrary objects are **refused**: there is
no canonical content model for them, so a stored digest could not support
a completion claim. There is no pickle path and no inline fallback.

.. warning::

   **Durability depends on the mount, not on this code.**
   ``LocalFileManager`` is durable only over a shared, persistent volume
   visible to every pod. A pod-local directory is not durable, and
   ``TempFileManager`` never is — it is for tests only.

.. note::

   **Known transport limitation.** The pinned file-manager interface
   (Phase 0 / TASK-2970) has no byte-range read: ``download_file``
   transfers a whole object. A bounded *page* read therefore transfers
   the full encoded blob and then decodes only the requested rows, so the
   **decoded** table is bounded but the **transfer** is not. That is why
   :attr:`ArtifactBlobStore.max_encoded_bytes` exists — an object larger
   than it is refused on its ``get_file_metadata`` size *before* any
   download starts, rather than being pulled into memory to find out.
"""

from __future__ import annotations

import asyncio
import io
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Tuple
from urllib.parse import quote

from parrot.interfaces.artifact_store import PayloadRefusal, PayloadResult
from pydantic import BaseModel, ConfigDict, Field

from .models import ArtifactKind, EvidenceRef, Limits, TaskMemoryError, TaskScope, utc_now
from .snapshots import (
    CHECKSUM_ALGORITHM,
    FINGERPRINT_ALGORITHM,
    blob_checksum,
    canonical_json_bytes,
    detect_kind,
    fingerprint_bytes,
    fingerprint_dataframe,
    unsafe_object_columns,
)

__all__ = (
    "DEFAULT_ARCHIVE_SEGMENT",
    "DEFAULT_BLOB_PREFIX",
    "DEFAULT_MAX_ENCODED_BYTES",
    "PARQUET_COMPRESSION",
    "BLOB_CORRUPTED",
    "BlobFormat",
    "BlobError",
    "BlobPublishError",
    "BlobImmutabilityError",
    "UnsupportedBlobPayload",
    "BlobRef",
    "StoredBlob",
    "ArtifactBlobStore",
    "DurableBlobSweeper",
)

logger = logging.getLogger(__name__)

#: Root path segment for every task-memory blob.
DEFAULT_BLOB_PREFIX: str = "task_memory/artifacts"

#: Path segment under which archived copies are kept. Blobs beneath it
#: are **never** swept as orphans: an archive is a reference, and it is
#: deliberately the one reference that has no index row pointing at it.
#: Sweeping by "nothing in the index mentions this" alone would delete
#: every archive on the first scan after it was written.
DEFAULT_ARCHIVE_SEGMENT: str = "_archive"

#: Largest encoded object this adapter will transfer in one operation.
#: Guards the *transport*, which the pinned interface cannot bound (see
#: the module note). Generous relative to the 64 MiB RAM snapshot cap,
#: because spilling exists precisely for payloads above it.
DEFAULT_MAX_ENCODED_BYTES: int = 512 * 1024 * 1024

#: Parquet codec. Snappy is fast and universally readable; the choice is
#: recorded in :class:`BlobRef` so a future change stays detectable.
PARQUET_COMPRESSION: str = "snappy"

#: Refusal reason for a blob whose bytes no longer match their recorded
#: checksum.
#:
#: Deliberately defined here rather than added to
#: :class:`~parrot.interfaces.artifact_store.PayloadRefusal`: that module
#: is another task's ownership. ``refusal`` is typed ``Optional[str]`` on
#: :class:`~parrot.interfaces.artifact_store.PayloadResult`, so a module
#: constant is contract-compliant. Promoting it is a reasonable
#: follow-up.
BLOB_CORRUPTED: str = "corrupted"


class BlobFormat(str, Enum):
    """On-disk encoding of a stored blob."""

    #: A DataFrame, written with ``pyarrow.parquet``.
    PARQUET = "parquet"
    #: Canonical sorted-key UTF-8 JSON.
    JSON = "json"
    #: UTF-8 text.
    TEXT = "text"

    @property
    def extension(self) -> str:
        """File extension for this format."""
        return {BlobFormat.PARQUET: "parquet", BlobFormat.JSON: "json", BlobFormat.TEXT: "txt"}[self]

    @property
    def is_tabular(self) -> bool:
        """Whether this format supports row-bounded page reads."""
        return self is BlobFormat.PARQUET


class BlobError(TaskMemoryError):
    """Base class for blob-storage failures."""


class UnsupportedBlobPayload(BlobError):
    """A value has no safe durable encoding.

    Binary blobs and arbitrary objects reach this: there is no canonical
    content model for them, so nothing stored could later support a
    completion claim. Refusing is the point — an inline or pickle
    fallback would produce durable bytes that prove nothing.
    """


class BlobPublishError(BlobError):
    """A blob could not be written and verified, so no reference exists.

    Raised whenever the write, the size check or the read-back checksum
    fails. The caller must **not** record a storage reference: an orphan
    blob is sweepable, a phantom reference is not.
    """


class BlobImmutabilityError(BlobError):
    """A published version's bytes were about to change.

    A version is written once. A retry with byte-identical content is
    accepted silently; anything else is a bug that would retroactively
    alter evidence a completed step already cites.
    """


class BlobRef(BaseModel):
    """A verified, immutable reference to stored bytes.

    Returned only after the bytes have been written *and* read back
    successfully, so possessing one of these means the payload exists.

    Attributes:
        key: Storage path, unique per ``(scope, artifact_id, version)``.
        blob_format: How the payload is encoded.
        checksum: ``ck_`` digest of the exact stored bytes.
        checksum_algorithm: Identity and version of the checksum rules.
        byte_size: Size of the stored object.
        content_fingerprint: ``fp_`` digest of the logical content, when
            the payload has a meaningful one. **Never** compared against
            :attr:`checksum`.
        fingerprint_algorithm: Identity and version of the fingerprint
            rules.
        kind: Evidence type the payload was published as.
        row_count: Rows in a tabular payload.
        compression: Parquet codec, when applicable.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(min_length=1, max_length=Limits.MAX_REASON)
    blob_format: BlobFormat
    checksum: str = Field(max_length=Limits.MAX_IDENTIFIER)
    checksum_algorithm: str = Field(default=CHECKSUM_ALGORITHM, max_length=Limits.MAX_IDENTIFIER)
    byte_size: int = Field(ge=0)
    content_fingerprint: Optional[str] = Field(default=None, max_length=Limits.MAX_IDENTIFIER)
    fingerprint_algorithm: Optional[str] = Field(default=None, max_length=Limits.MAX_IDENTIFIER)
    kind: ArtifactKind = ArtifactKind.OBJECT
    row_count: Optional[int] = Field(default=None, ge=0)
    compression: Optional[str] = Field(default=None, max_length=Limits.MAX_IDENTIFIER)


# ─────────────────────────────────────────────────────────────
# Encoding
# ─────────────────────────────────────────────────────────────


def _encode_dataframe(df: Any) -> Tuple[bytes, BlobFormat, str, int]:
    """Encode a DataFrame as Parquet.

    Args:
        df: The frame to encode.

    Returns:
        ``(payload, format, content_fingerprint, row_count)``.

    Raises:
        UnsupportedBlobPayload: If the frame holds nested mutable object
            cells. Such a frame can never carry verifiable evidence
            (``copy(deep=True)`` does not detach those cells and pandas
            hashes them by ``repr``), so storing it durably would create
            bytes that look authoritative and prove nothing. Checked
            before Arrow so the message names the offending columns
            rather than surfacing a conversion error.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    unsafe = unsafe_object_columns(df)
    if unsafe:
        raise UnsupportedBlobPayload(
            f"columns {list(unsafe)} hold mutable or non-canonical objects; "
            "no fingerprint over this frame proves content integrity, so it "
            "must not be stored as durable evidence"
        )

    fingerprint = fingerprint_dataframe(df)
    try:
        table = pa.Table.from_pandas(df, preserve_index=True)
    except Exception as exc:  # noqa: BLE001 — any conversion failure is one answer
        raise UnsupportedBlobPayload(f"DataFrame cannot be encoded as Parquet: {exc}") from exc

    sink = io.BytesIO()
    pq.write_table(table, sink, compression=PARQUET_COMPRESSION)
    return sink.getvalue(), BlobFormat.PARQUET, fingerprint, int(df.shape[0])


def _encode_payload(value: Any, kind: ArtifactKind) -> Tuple[bytes, BlobFormat, str, Optional[int]]:
    """Encode a supported value for durable storage.

    Args:
        value: The payload.
        kind: Its evidence type.

    Returns:
        ``(payload, format, content_fingerprint, row_count)``.

    Raises:
        UnsupportedBlobPayload: For binary values, arbitrary objects, or
            anything without a canonical encoding. There is deliberately
            no pickle path.
    """
    if kind is ArtifactKind.DATAFRAME:
        return _encode_dataframe(value)
    if kind is ArtifactKind.TEXT:
        encoded = value.encode("utf-8")
        return encoded, BlobFormat.TEXT, fingerprint_bytes(encoded), None
    if kind is ArtifactKind.JSON:
        encoded = canonical_json_bytes(value)
        return encoded, BlobFormat.JSON, fingerprint_bytes(encoded), None
    raise UnsupportedBlobPayload(
        f"{kind.value!r} payloads have no canonical durable encoding; "
        "only DataFrame, JSON and text may be stored as evidence"
    )


def _decode_full(payload: bytes, blob_format: BlobFormat) -> Any:
    """Decode a whole stored payload.

    Args:
        payload: The stored bytes.
        blob_format: How they are encoded.

    Returns:
        The decoded value.
    """
    if blob_format is BlobFormat.PARQUET:
        import pyarrow.parquet as pq

        return pq.ParquetFile(io.BytesIO(payload)).read().to_pandas()
    if blob_format is BlobFormat.JSON:
        import orjson

        return orjson.loads(payload)
    return payload.decode("utf-8")


def _decode_page(payload: bytes, offset: int, limit: int) -> Tuple[Any, int]:
    """Decode only a bounded row window of a Parquet payload.

    Reads through ``iter_batches`` and slices, so a small page of a large
    table never materializes the whole table. ``ParquetFile.read()`` is
    deliberately not used — it would decode every row before the slice.

    Args:
        payload: The stored Parquet bytes.
        offset: First row to return.
        limit: Maximum rows to return.

    Returns:
        ``(dataframe, total_rows)``.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(io.BytesIO(payload))
    total_rows = int(parquet.metadata.num_rows)
    schema = parquet.schema_arrow

    collected: list = []
    remaining = limit
    scanned = 0
    for batch in parquet.iter_batches(batch_size=max(1, min(limit, 1024))):
        rows = batch.num_rows
        if scanned + rows <= offset:
            scanned += rows
            continue
        start = max(0, offset - scanned)
        take = min(remaining, rows - start)
        if take > 0:
            collected.append(batch.slice(start, take))
            remaining -= take
        scanned += rows
        if remaining <= 0:
            break

    table = pa.Table.from_batches(collected, schema=schema) if collected else schema.empty_table()
    return table.to_pandas(), total_rows


def _measure_decoded(value: Any, blob_format: BlobFormat) -> int:
    """Estimate the byte footprint of a decoded value.

    Args:
        value: The decoded payload.
        blob_format: How it was stored.

    Returns:
        A byte count. For a frame this is pandas' deep estimate, which is
        an estimate; for text and JSON it is the exact canonical size.
    """
    if blob_format is BlobFormat.PARQUET:
        return int(value.memory_usage(deep=True).sum())
    if blob_format is BlobFormat.JSON:
        return len(canonical_json_bytes(value))
    return len(value.encode("utf-8"))


# ─────────────────────────────────────────────────────────────
# The store
# ─────────────────────────────────────────────────────────────


class ArtifactBlobStore:
    """Immutable, verified blob storage for durable task evidence.

    Wraps any ``FileManagerInterface`` implementation using only the
    operations Phase 0 pinned against the installed navigator-api:
    ``create_from_bytes``, ``download_file``, ``get_file_metadata``,
    ``exists`` and ``delete_file``. No streaming or byte-range API is
    assumed, because the interface has none.
    """

    def __init__(
        self,
        file_manager: Any,
        *,
        prefix: str = DEFAULT_BLOB_PREFIX,
        max_encoded_bytes: int = DEFAULT_MAX_ENCODED_BYTES,
    ) -> None:
        """Initialize the store.

        Args:
            file_manager: Any ``FileManagerInterface`` implementation.
                Durable only over a shared persistent mount; a pod-local
                directory or ``TempFileManager`` is not durable.
            prefix: Root path segment for every blob.
            max_encoded_bytes: Largest encoded object to write or
                transfer in one operation.

        Raises:
            ValueError: If ``max_encoded_bytes`` is not positive.
        """
        if max_encoded_bytes <= 0:
            raise ValueError(f"max_encoded_bytes must be > 0, got {max_encoded_bytes}")
        self._fm = file_manager
        self._prefix = prefix.strip("/")
        self.max_encoded_bytes = max_encoded_bytes
        self.logger = logging.getLogger(__name__)

    # ── naming ───────────────────────────────────────────────────────

    @staticmethod
    def _segment(value: str) -> str:
        """Encode one value as a single, inert path segment.

        Percent-encoding with no safe characters removes ``/``, so a
        value can never add path depth. That alone is **not** sufficient:
        ``quote`` leaves ``.`` untouched because it is an unreserved
        character, so a component of exactly ``".."`` would survive as a
        real parent-directory segment. Dot-only segments are therefore
        encoded explicitly.

        Args:
            value: The raw component.

        Returns:
            A segment that is neither ``.`` nor ``..`` and contains no
            separator. The mapping stays injective, so distinct inputs
            keep producing distinct keys.
        """
        encoded = quote(str(value), safe="")
        if encoded and set(encoded) == {"."}:
            return encoded.replace(".", "%2E")
        return encoded

    def blob_key(self, scope: TaskScope, ref: EvidenceRef, blob_format: BlobFormat) -> str:
        """Return the immutable storage key for one artifact version.

        Every path component is encoded by :meth:`_segment`, so a value
        containing ``/`` — or consisting of ``..`` — can neither escape
        its scope's subtree nor collide with a different scope. The
        encoding is injective, so distinct scopes always yield distinct
        keys.

        Args:
            scope: Trusted runtime scope.
            ref: The exact artifact version.
            blob_format: Encoding, which fixes the extension.

        Returns:
            A storage key of the form
            ``{prefix}/{chatbot}/{user}/{session}/{artifact_id}/v{n}.{ext}``.
        """
        q = self._segment
        return (
            f"{self._prefix}/{q(scope.chatbot_id)}/{q(scope.user_id)}/{q(scope.session_id)}"
            f"/{q(ref.artifact_id)}/v{ref.version}.{blob_format.extension}"
        )

    # ── publish ──────────────────────────────────────────────────────

    async def publish(
        self,
        scope: TaskScope,
        ref: EvidenceRef,
        value: Any,
        *,
        kind: Optional[ArtifactKind] = None,
    ) -> BlobRef:
        """Write, verify and reference one artifact version's bytes.

        The order is the guarantee: encode → write → stat → read back →
        checksum → *then* return a reference. Nothing here mutates an
        index; the caller commits the alias/version row, the evidence
        metadata and the ``artifact_registered`` event together, on one
        connection, only after this returns.

        A retry with byte-identical content succeeds without rewriting.

        Args:
            scope: Trusted runtime scope.
            ref: The exact artifact version.
            value: The payload.
            kind: Force an evidence type instead of detecting one.

        Returns:
            A verified :class:`BlobRef`.

        Raises:
            UnsupportedBlobPayload: If the value has no canonical durable
                encoding.
            LimitExceeded: If the encoded payload exceeds
                :attr:`max_encoded_bytes`.
            BlobImmutabilityError: If a different payload is already
                stored for this version.
            BlobPublishError: If the write, the size check or the
                read-back verification failed. No reference is returned,
                and the partial object is best-effort removed — an orphan
                is sweepable either way.
        """
        detected = detect_kind(value)
        effective = kind or detected
        if kind is not None and kind is not detected:
            raise UnsupportedBlobPayload(
                f"declared kind {kind.value!r} does not match the value's actual type {detected.value!r}"
            )

        # Encoding and fingerprinting are CPU-bound and dominate cost for
        # large frames, so they never run on the event loop.
        payload, blob_format, fingerprint, row_count = await asyncio.to_thread(_encode_payload, value, effective)

        if len(payload) > self.max_encoded_bytes:
            from .models import LimitExceeded

            raise LimitExceeded(
                "encoded blob",
                self.max_encoded_bytes,
                len(payload),
                "reduce the payload or raise max_encoded_bytes",
            )

        checksum = blob_checksum(payload)
        key = self.blob_key(scope, ref, blob_format)

        existing = await self._verify_existing(key, checksum, ref)
        if existing is not None:
            return BlobRef(
                key=key,
                blob_format=blob_format,
                checksum=checksum,
                byte_size=len(payload),
                content_fingerprint=fingerprint,
                fingerprint_algorithm=FINGERPRINT_ALGORITHM,
                kind=effective,
                row_count=row_count,
                compression=PARQUET_COMPRESSION if blob_format is BlobFormat.PARQUET else None,
            )

        try:
            written = await self._fm.create_from_bytes(key, payload)
        except Exception as exc:  # noqa: BLE001 — every write failure is one answer
            raise BlobPublishError(f"failed to write blob {key!r}: {exc}") from exc
        if written is False:
            raise BlobPublishError(f"file manager declined to write blob {key!r}")

        try:
            await self._verify_written(key, payload, checksum)
        except BlobPublishError:
            # Remove the unverified object. Best effort: an orphan blob is
            # expected after a crash and is swept later, so a failed
            # cleanup must not mask the publish failure.
            await self._best_effort_delete(key)
            raise

        return BlobRef(
            key=key,
            blob_format=blob_format,
            checksum=checksum,
            byte_size=len(payload),
            content_fingerprint=fingerprint,
            fingerprint_algorithm=FINGERPRINT_ALGORITHM,
            kind=effective,
            row_count=row_count,
            compression=PARQUET_COMPRESSION if blob_format is BlobFormat.PARQUET else None,
        )

    async def _verify_existing(self, key: str, checksum: str, ref: EvidenceRef) -> Optional[bool]:
        """Check whether this version is already stored, and whether it matches.

        Args:
            key: Storage key.
            checksum: Checksum of the payload about to be written.
            ref: The version, for the error message.

        Returns:
            ``True`` when a byte-identical object already exists (an
            idempotent retry), or ``None`` when nothing is stored.

        Raises:
            BlobImmutabilityError: If a *different* payload is stored for
                this version.
        """
        try:
            if not await self._fm.exists(key):
                return None
        except Exception:  # noqa: BLE001 — treat an unreadable probe as absent
            return None

        try:
            stored = await self._download(key)
        except Exception as exc:  # noqa: BLE001
            raise BlobImmutabilityError(
                f"version {ref} already has stored bytes at {key!r} that cannot be read back " f"for comparison: {exc}"
            ) from exc

        if blob_checksum(stored) == checksum:
            self.logger.debug("Blob %s already published with identical bytes; treating as a retry", key)
            return True
        raise BlobImmutabilityError(
            f"version {ref} is already stored with different content at {key!r}; "
            "artifact versions are immutable, so a changed payload must be a new version"
        )

    async def _verify_written(self, key: str, payload: bytes, checksum: str) -> None:
        """Confirm the stored object is readable and byte-identical.

        Args:
            key: Storage key.
            payload: The bytes that were written.
            checksum: Their checksum.

        Raises:
            BlobPublishError: If the object cannot be stat'd or read
                back, its size differs, or its checksum differs.
        """
        try:
            metadata = await self._fm.get_file_metadata(key)
        except Exception as exc:  # noqa: BLE001
            raise BlobPublishError(f"blob {key!r} could not be stat'd after writing: {exc}") from exc

        size = getattr(metadata, "size", None)
        if size is not None and int(size) != len(payload):
            raise BlobPublishError(f"blob {key!r} stored {size} bytes, expected {len(payload)}")

        try:
            stored = await self._download(key)
        except Exception as exc:  # noqa: BLE001
            raise BlobPublishError(f"blob {key!r} could not be read back after writing: {exc}") from exc

        if blob_checksum(stored) != checksum:
            raise BlobPublishError(
                f"blob {key!r} failed checksum verification after writing; the stored bytes "
                "do not match what was sent"
            )

    # ── load ─────────────────────────────────────────────────────────

    async def load(
        self,
        scope: TaskScope,
        ref: EvidenceRef,
        blob: BlobRef,
        *,
        max_bytes: int,
        offset: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> PayloadResult:
        """Materialize a stored payload under explicit byte bounds.

        Enforcement happens in this order, and the order matters:

        1. ``max_bytes == 0`` refuses immediately — never rehydrate.
        2. The object's ``get_file_metadata`` size is checked against
           :attr:`max_encoded_bytes` **before any download**. This is the
           only bound available on the transfer, because the pinned
           interface has no byte-range read.
        3. The checksum of the transferred bytes is verified.
        4. For a tabular payload, only the requested rows are decoded.
        5. The decoded size is checked against ``max_bytes``.

        A refusal never carries a payload.

        Args:
            scope: Trusted runtime scope.
            ref: The exact artifact version.
            blob: Its verified reference.
            max_bytes: Ceiling on the decoded payload. ``0`` means never
                materialize.
            offset: First row, for a tabular page read.
            limit: Row count, for a tabular page read.

        Returns:
            A :class:`~parrot.interfaces.artifact_store.PayloadResult`
            carrying either the payload or a refusal reason.

        Raises:
            ValueError: If ``max_bytes`` is negative, ``offset`` is
                negative, or ``limit`` is not positive.
        """
        if max_bytes < 0:
            raise ValueError(f"max_bytes must be >= 0, got {max_bytes}")
        if offset is not None and offset < 0:
            raise ValueError(f"offset must be >= 0, got {offset}")
        if limit is not None and limit < 1:
            raise ValueError(f"limit must be >= 1, got {limit}")

        paging = offset is not None or limit is not None
        if paging and not blob.blob_format.is_tabular:
            return self._refuse(
                ref,
                blob,
                PayloadRefusal.UNSUPPORTED,
                f"{blob.blob_format.value} payloads have no rows to page",
            )

        if max_bytes == 0:
            return self._refuse(
                ref,
                blob,
                PayloadRefusal.TOO_LARGE,
                "raw reads are disabled (max_bytes=0); use wm_compute_and_store instead",
                byte_size=blob.byte_size,
            )

        # Size pre-check BEFORE any transfer.
        try:
            metadata = await self._fm.get_file_metadata(blob.key)
        except FileNotFoundError:
            return self._refuse(ref, blob, PayloadRefusal.MISSING, f"stored bytes for {ref} are gone")
        except Exception as exc:  # noqa: BLE001
            return self._refuse(ref, blob, PayloadRefusal.MISSING, f"stored bytes for {ref} are unreadable: {exc}")

        encoded_size = int(getattr(metadata, "size", blob.byte_size) or 0)
        if encoded_size > self.max_encoded_bytes:
            return self._refuse(
                ref,
                blob,
                PayloadRefusal.TOO_LARGE,
                (
                    f"encoded object is {encoded_size} bytes, above the "
                    f"{self.max_encoded_bytes}-byte transfer ceiling; use wm_compute_and_store"
                ),
                byte_size=encoded_size,
            )

        # For a whole-value read of a non-tabular payload the encoded size
        # already bounds the decoded size closely enough to refuse here,
        # before spending the transfer.
        if not paging and not blob.blob_format.is_tabular and encoded_size > max_bytes:
            return self._refuse(
                ref,
                blob,
                PayloadRefusal.TOO_LARGE,
                (
                    f"payload is {encoded_size} bytes, above the {max_bytes}-byte ceiling; "
                    "use wm_compute_and_store instead of rehydrating it"
                ),
                byte_size=encoded_size,
            )

        try:
            payload_bytes = await self._download(blob.key)
        except FileNotFoundError:
            return self._refuse(ref, blob, PayloadRefusal.MISSING, f"stored bytes for {ref} are gone")
        except Exception as exc:  # noqa: BLE001
            return self._refuse(ref, blob, PayloadRefusal.MISSING, f"stored bytes for {ref} are unreadable: {exc}")

        if blob_checksum(payload_bytes) != blob.checksum:
            return self._refuse(
                ref,
                blob,
                BLOB_CORRUPTED,
                (
                    f"stored bytes for {ref} do not match their recorded checksum; "
                    "the payload is not trustworthy evidence"
                ),
                byte_size=len(payload_bytes),
            )

        if paging:
            effective_offset = offset or 0
            effective_limit = limit if limit is not None else 1
            decoded, total_rows = await asyncio.to_thread(
                _decode_page, payload_bytes, effective_offset, effective_limit
            )
            decoded_size = await asyncio.to_thread(_measure_decoded, decoded, blob.blob_format)
            if decoded_size > max_bytes:
                return self._refuse(
                    ref,
                    blob,
                    PayloadRefusal.TOO_LARGE,
                    (
                        f"the requested page decodes to {decoded_size} bytes, above the "
                        f"{max_bytes}-byte ceiling; request fewer rows"
                    ),
                    byte_size=encoded_size,
                )
            return PayloadResult(
                ref=ref,
                kind=blob.kind,
                payload=decoded,
                byte_size=encoded_size,
                returned_bytes=decoded_size,
                offset=effective_offset,
                limit=effective_limit,
                total_rows=total_rows,
                truncated=(effective_offset > 0 or len(decoded) < total_rows),
            )

        decoded = await asyncio.to_thread(_decode_full, payload_bytes, blob.blob_format)
        decoded_size = await asyncio.to_thread(_measure_decoded, decoded, blob.blob_format)
        if decoded_size > max_bytes:
            return self._refuse(
                ref,
                blob,
                PayloadRefusal.TOO_LARGE,
                (
                    f"payload decodes to {decoded_size} bytes, above the {max_bytes}-byte ceiling; "
                    "read a bounded page or use wm_compute_and_store"
                ),
                byte_size=encoded_size,
            )

        total_rows = blob.row_count if blob.blob_format.is_tabular else None
        return PayloadResult(
            ref=ref,
            kind=blob.kind,
            payload=decoded,
            byte_size=encoded_size,
            returned_bytes=decoded_size,
            total_rows=total_rows,
            truncated=False,
        )

    @staticmethod
    def _refuse(
        ref: EvidenceRef,
        blob: BlobRef,
        reason: str,
        guidance: str,
        *,
        byte_size: Optional[int] = None,
    ) -> PayloadResult:
        """Build a refusal that carries no payload.

        Args:
            ref: The version that was requested.
            blob: Its reference.
            reason: A refusal constant.
            guidance: What the caller should do instead.
            byte_size: Observed size, so the caller can tell how far over
                a ceiling it was.

        Returns:
            A payload-free :class:`PayloadResult`.
        """
        return PayloadResult(
            ref=ref,
            kind=blob.kind,
            payload=None,
            refusal=reason,
            byte_size=byte_size,
            guidance=guidance,
        )

    # ── deletion and archive ─────────────────────────────────────────

    async def delete(self, scope: TaskScope, blob: BlobRef) -> bool:
        """Delete one version's stored bytes.

        Retention calls this only after recording its intent, and only
        when nothing pins the version.

        Args:
            scope: Trusted runtime scope.
            blob: The reference to delete.

        Returns:
            ``True`` when bytes were removed, ``False`` when there were
            none to remove. A missing object is not an error: retention
            retries must be idempotent.
        """
        try:
            return bool(await self._fm.delete_file(blob.key))
        except FileNotFoundError:
            return False
        except Exception as exc:  # noqa: BLE001 — deletion is best effort and idempotent
            self.logger.warning("Failed to delete blob %s: %s", blob.key, exc)
            return False

    async def archive(self, scope: TaskScope, blob: BlobRef, destination_key: str) -> BlobRef:
        """Copy a blob to an archive location and verify it landed.

        Terminal deletion may only proceed after the archive is verified
        (spec §2 Retention), so this returns a reference only when the
        copy has been read back and checksummed.

        Args:
            scope: Trusted runtime scope.
            blob: The reference to archive.
            destination_key: Archive storage key.

        Returns:
            A verified :class:`BlobRef` for the archived copy.

        Raises:
            BlobPublishError: If the source cannot be read, or the copy
                cannot be written and verified. The caller must not treat
                an unverified archive as permission to delete.
        """
        try:
            payload = await self._download(blob.key)
        except Exception as exc:  # noqa: BLE001
            raise BlobPublishError(f"cannot archive {blob.key!r}: source unreadable: {exc}") from exc

        if blob_checksum(payload) != blob.checksum:
            raise BlobPublishError(f"cannot archive {blob.key!r}: source bytes do not match their recorded checksum")

        try:
            written = await self._fm.create_from_bytes(destination_key, payload)
        except Exception as exc:  # noqa: BLE001
            raise BlobPublishError(f"failed to write archive {destination_key!r}: {exc}") from exc
        if written is False:
            raise BlobPublishError(f"file manager declined to write archive {destination_key!r}")

        try:
            await self._verify_written(destination_key, payload, blob.checksum)
        except BlobPublishError:
            await self._best_effort_delete(destination_key)
            raise

        return blob.model_copy(update={"key": destination_key})

    async def exists(self, blob: BlobRef) -> bool:
        """Whether a blob's bytes are present.

        Args:
            blob: The reference to probe.

        Returns:
            ``True`` when the object exists.
        """
        try:
            return bool(await self._fm.exists(blob.key))
        except Exception:  # noqa: BLE001 — an unreadable probe is not proof of presence
            return False

    # ── internals ────────────────────────────────────────────────────

    async def _download(self, key: str) -> bytes:
        """Transfer a whole object into memory.

        The pinned interface offers no byte-range read, so callers must
        bound the transfer with a ``get_file_metadata`` size check first.

        Args:
            key: Storage key.

        Returns:
            The stored bytes.
        """
        buffer = io.BytesIO()
        await self._fm.download_file(key, buffer)
        return buffer.getvalue()

    async def _best_effort_delete(self, key: str) -> None:
        """Remove an unverified object, ignoring failure.

        Args:
            key: Storage key.
        """
        try:
            await self._fm.delete_file(key)
        except Exception as exc:  # noqa: BLE001 — cleanup must not mask the real failure
            self.logger.warning("Could not clean up unverified blob %s: %s", key, exc)

    # ── retention support ────────────────────────────────────────────

    def scope_prefix(self, scope: TaskScope) -> str:
        """Return the storage sub-tree holding one scope's blobs.

        Args:
            scope: Trusted runtime scope.

        Returns:
            The prefix, without a trailing separator.
        """
        q = self._segment
        return f"{self._prefix}/{q(scope.chatbot_id)}/{q(scope.user_id)}/{q(scope.session_id)}"

    def archive_prefix(self, scope: TaskScope, *, segment: str = DEFAULT_ARCHIVE_SEGMENT) -> str:
        """Return the sub-tree holding one scope's archived copies.

        Args:
            scope: Trusted runtime scope.
            segment: Archive segment name.

        Returns:
            The archive prefix.
        """
        return f"{self.scope_prefix(scope)}/{self._segment(segment)}"

    async def list_stored(self, scope: TaskScope) -> Tuple["StoredBlob", ...]:
        """Enumerate every object currently stored for a scope.

        Uses ``find_files(prefix=...)``, which is recursive — verified
        against the installed navigator implementation, which delegates
        to ``Path.rglob``. ``list_files`` is deliberately **not** used:
        it is non-recursive and returns nothing for a directory that
        holds only sub-directories, so it would report every blob as
        absent and, through the orphan rule, as sweepable.

        Args:
            scope: Trusted runtime scope.

        Returns:
            One :class:`StoredBlob` per object, oldest first. An
            unreadable or absent prefix yields an empty tuple rather
            than raising: "I could not list" must never be reported as
            "there is nothing here", which for a sweeper would be a
            licence to delete.
        """
        prefix = self.scope_prefix(scope)
        try:
            found = await self._fm.find_files(prefix=prefix)
        except FileNotFoundError:
            return ()
        except Exception as exc:  # noqa: BLE001 — see docstring
            self.logger.warning("Could not enumerate blobs under %s: %s", prefix, exc)
            return ()

        stored: list = []
        for meta in found or ():
            key = getattr(meta, "path", None)
            if not key:
                continue
            stored.append(
                StoredBlob(
                    key=str(key),
                    byte_size=int(getattr(meta, "size", 0) or 0),
                    modified_at=_as_utc(getattr(meta, "modified_at", None)),
                )
            )
        return tuple(sorted(stored, key=lambda b: b.key))


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Normalize a storage timestamp to an aware UTC datetime.

    File managers report naive local timestamps (``LocalFileManager``
    builds them from ``st_mtime``), while every retention threshold is
    aware and UTC. Comparing the two raises, so the coercion happens here
    — at the boundary where the naive value enters — rather than being
    defended against by each consumer.

    Args:
        value: The reported timestamp, if any.

    Returns:
        An aware UTC datetime, or ``None``.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.astimezone(timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class StoredBlob:
    """One object found in storage, independent of any index row.

    Attributes:
        key: Its storage path.
        byte_size: Size in bytes.
        modified_at: Last modification time, when storage reports one.
    """

    key: str
    byte_size: int = 0
    modified_at: Optional[datetime] = None


class DurableBlobSweeper:
    """Finds and removes orphan blobs, conservatively.

    Implements :class:`~.retention.BlobSweeper`. A blob is an orphan only
    when **all three** references are absent — no live index row, no
    in-flight publish lease, no archive. Each is checked independently
    because each fails differently:

    - the index is authoritative but says nothing about a publish that
      has written its bytes and not yet committed its row;
    - a publish lease covers exactly that window;
    - an archive is a reference with deliberately *no* index row, so a
      sweeper that only consulted the index would delete every archive.

    Every uncertainty resolves to "not an orphan". A blob wrongly kept is
    swept on the next pass once the doubt clears; a blob wrongly deleted
    is gone.

    Args:
        blobs: The blob store, for enumeration and deletion.
        live_refs: Async callable returning the storage keys the index
            still references for a scope.
        publish_lease: Optional async predicate answering "is a publish
            in flight for this key?". Without one, no key is treated as
            leased — so wire it in any deployment where a publish can
            race a sweep.
        archive_segment: Path segment marking archived copies.
        clock: Injected clock.
    """

    def __init__(
        self,
        blobs: "ArtifactBlobStore",
        *,
        live_refs: Any,
        publish_lease: Optional[Any] = None,
        archive_segment: str = DEFAULT_ARCHIVE_SEGMENT,
        clock: Optional[Any] = None,
    ) -> None:
        """Initialize the sweeper."""
        self._blobs = blobs
        self._live_refs = live_refs
        self._publish_lease = publish_lease
        self._archive_segment = archive_segment
        self._clock = clock
        self.logger = logging.getLogger(__name__)

    async def list_orphans(self, scope: TaskScope) -> Tuple[Any, ...]:
        """Return candidate orphans with their reference flags resolved.

        Args:
            scope: Trusted runtime scope.

        Returns:
            One ``BlobRetentionView`` per stored object. The grace period
            is applied by the pure selector, not here.
        """
        from .retention import BlobRetentionView

        stored = await self._blobs.list_stored(scope)
        if not stored:
            return ()

        try:
            live = frozenset(await self._live_refs(scope))
        except Exception as exc:  # noqa: BLE001 — an unreadable index is not an empty one
            self.logger.warning("Could not read live storage references: %s; skipping sweep", exc)
            return ()

        archive_root = self._blobs.archive_prefix(scope, segment=self._archive_segment) + "/"
        now = self._clock() if self._clock is not None else None

        views: list = []
        for blob in stored:
            leased = False
            if self._publish_lease is not None:
                try:
                    leased = bool(await self._publish_lease(scope, blob.key))
                except Exception as exc:  # noqa: BLE001 — unknown means "leased"
                    self.logger.warning("Publish-lease probe failed for %s: %s", blob.key, exc)
                    leased = True
            views.append(
                BlobRetentionView(
                    scope=scope,
                    storage_ref=blob.key,
                    written_at=blob.modified_at or now or utc_now(),
                    has_live_index=blob.key in live,
                    has_publish_lease=leased,
                    has_archive_reference=blob.key.startswith(archive_root),
                )
            )
        return tuple(views)

    async def sweep(self, scope: TaskScope, storage_ref: str) -> bool:
        """Delete one orphan blob.

        Args:
            scope: Trusted runtime scope.
            storage_ref: The object to delete.

        Returns:
            ``True`` when bytes were removed. A missing object returns
            ``False`` rather than raising, so a retry after a partial
            sweep converges.
        """
        if not storage_ref.startswith(self._blobs.scope_prefix(scope) + "/"):
            # Refuses to delete outside the scope's own sub-tree even if
            # a caller hands it a key from elsewhere.
            self.logger.warning("Refusing to sweep %s: outside the scope's sub-tree", storage_ref)
            return False
        try:
            return bool(await self._blobs._fm.delete_file(storage_ref))
        except FileNotFoundError:
            return False
        except Exception as exc:  # noqa: BLE001 — sweeping is best effort and idempotent
            self.logger.warning("Failed to sweep orphan blob %s: %s", storage_ref, exc)
            return False
