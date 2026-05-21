"""Async blob storage abstraction for FieldType.REST uploads.

Provides ``AbstractBlobStorage`` (ABC) plus concrete backends — ``S3BlobStorage``,
``GCSBlobStorage``, ``LocalBlobStorage``, ``TempBlobStorage`` — each implemented
as a thin adapter over the matching ``navigator.utils.file`` ``FileManager``.

Credential resolution and provider-specific I/O live in the ``FileManager``
implementations; this module only handles:

* ``BlobMetadata`` → object key construction (``{prefix}{form_id}/{field_id}/{uuid}``).
* ``blob_ref`` round-tripping (scheme + key).
* The ``pre_persist_hook`` extension point.

The ``put`` contract collects the inbound async byte stream into memory before
writing — sufficient for V1 form uploads, which are size-bounded by the
multipart parser upstream. Streaming/multipart uploads are delegated to the
FileManager when applicable.
"""

from __future__ import annotations

import logging
import os
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from io import BytesIO
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class BlobRejectedError(Exception):
    """Raised by ``AbstractBlobStorage.pre_persist_hook`` to abort a ``put``.

    Subclasses may raise this from their hook implementation to prevent the
    blob from being persisted. The upload handler will propagate this error
    to the caller.
    """


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class BlobMetadata(BaseModel):
    """Metadata associated with a persisted blob.

    Attributes:
        form_id: Identifier of the parent form.
        field_id: Identifier of the form field that owns this blob.
        submission_id: Optional submission ID for audit correlation.
        tenant: Optional tenant slug for multi-tenant deployments.
        content_type: MIME type of the stored content (e.g. ``image/jpeg``).
        size_bytes: Size of the content in bytes.
    """

    model_config = ConfigDict(extra="forbid")

    form_id: str
    field_id: str
    submission_id: str | None = None
    tenant: str | None = None
    content_type: str
    size_bytes: int


class PrePersistContext(BaseModel):
    """Context passed to ``AbstractBlobStorage.pre_persist_hook`` before writing.

    In V1 the default ``pre_persist_hook`` is a no-op. V2 will use this
    context to perform AV/content-scanning before persisting the blob.

    Attributes:
        metadata: Full blob metadata.
        content_preview: First N bytes of the content for scanning.
            ``None`` disables preview-based scanning.
    """

    model_config = ConfigDict(extra="forbid")

    metadata: BlobMetadata
    content_preview: bytes | None = None


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------


class AbstractBlobStorage(ABC):
    """Abstract async blob storage.

    Concrete implementations: ``S3BlobStorage``, ``GCSBlobStorage``,
    ``LocalBlobStorage``, ``TempBlobStorage``, and any user-supplied backend
    inheriting from this class.

    All methods are async. The ``pre_persist_hook`` is called by ``put``
    before writing; subclasses may raise ``BlobRejectedError`` to abort.
    """

    @abstractmethod
    async def put(
        self,
        stream: AsyncIterator[bytes],
        *,
        metadata: BlobMetadata,
    ) -> str:
        """Persist a blob and return a stable blob reference.

        The stream is consumed from the async iterator. V1 implementations
        collect all chunks before writing; future revisions may stream.

        The ``pre_persist_hook`` is invoked before writing begins; if it
        raises ``BlobRejectedError`` the blob is NOT written and the error
        propagates to the caller.

        Args:
            stream: Async byte-chunk iterator.
            metadata: Contextual metadata for the blob.

        Returns:
            Stable blob reference string (implementation-defined format).

        Raises:
            BlobRejectedError: If ``pre_persist_hook`` rejects the blob.
        """

    @abstractmethod
    async def get(self, blob_ref: str) -> AsyncIterator[bytes]:
        """Stream a blob by reference.

        Args:
            blob_ref: Blob reference returned by ``put``.

        Returns:
            Async iterator of byte chunks.
        """

    @abstractmethod
    async def delete(self, blob_ref: str) -> None:
        """Delete a blob by reference. Idempotent — no error if missing.

        Args:
            blob_ref: Blob reference returned by ``put``.
        """

    async def pre_persist_hook(self, ctx: PrePersistContext) -> None:
        """Pre-write hook for AV/content-scanning. V1 default: no-op.

        Subclasses MAY override this to inspect the blob before it is
        written. Raise ``BlobRejectedError`` to prevent the write.

        Args:
            ctx: Pre-persist context (metadata + optional preview bytes).

        Returns:
            None (always, in V1 default implementation).
        """
        return None


# ---------------------------------------------------------------------------
# Manager-backed base
# ---------------------------------------------------------------------------


_CHUNK_SIZE = 64 * 1024


class _ManagerBackedBlobStorage(AbstractBlobStorage):
    """Adapter that delegates persistence to a ``FileManagerInterface``.

    Concrete subclasses (one per backend) supply the manager instance, the
    URI scheme used to build ``blob_ref`` strings, and — for ref shapes
    that embed a bucket — the bucket identifier.

    Subclasses must set:

    * ``scheme`` — class-level URI scheme (e.g. ``"s3"``, ``"gs"``, ``"file"``,
      ``"temp"``).
    * ``self._manager`` — instance attribute holding the ``FileManager``.
    * ``self._bucket`` — instance attribute or ``None`` for backends without
      a bucket concept (Local, Temp).
    * ``self._prefix`` — leading prefix prepended to every key.

    The default ``get()`` downloads through the manager into an in-memory
    buffer; backends with destructive ``download_file`` semantics
    (``TempFileManager`` moves the file) override ``get()`` directly.
    """

    scheme: str = ""

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self._manager: Any = None
        self._bucket: str | None = None
        self._prefix: str = ""

    # -- key + ref helpers -------------------------------------------------

    def _build_key(self, metadata: BlobMetadata) -> str:
        """Construct the storage key for a new blob.

        Returns:
            ``{prefix}{form_id}/{field_id}/{uuid}`` — the relative key passed
            verbatim to the FileManager (managers are instantiated with an
            empty prefix so they do not re-prefix the key).
        """
        blob_id = str(uuid.uuid4())
        return f"{self._prefix}{metadata.form_id}/{metadata.field_id}/{blob_id}"

    def _to_ref(self, key: str) -> str:
        """Format a blob reference for a freshly-written key.

        Bucket-aware backends produce ``{scheme}://{bucket}/{key}``;
        bucket-less backends produce ``{scheme}://{key}``.
        """
        if self._bucket:
            return f"{self.scheme}://{self._bucket}/{key}"
        return f"{self.scheme}://{key}"

    def _from_ref(self, blob_ref: str) -> str:
        """Extract the storage key from a ``blob_ref`` string.

        Inverse of :meth:`_to_ref`. Returns the key in the form the
        FileManager understands (i.e. with the prefix still attached, since
        the manager prefix is empty by construction).
        """
        expected_prefix = f"{self.scheme}://"
        if not blob_ref.startswith(expected_prefix):
            raise ValueError(
                f"blob_ref {blob_ref!r} does not match scheme {self.scheme!r}"
            )
        remainder = blob_ref[len(expected_prefix):]
        if self._bucket:
            # Strip the leading "{bucket}/" segment
            try:
                _, key = remainder.split("/", 1)
            except ValueError as exc:
                raise ValueError(
                    f"blob_ref {blob_ref!r} is missing the key component"
                ) from exc
            return key
        return remainder

    # -- AbstractBlobStorage implementation --------------------------------

    async def put(
        self,
        stream: AsyncIterator[bytes],
        *,
        metadata: BlobMetadata,
    ) -> str:
        chunks: list[bytes] = []
        async for chunk in stream:
            chunks.append(chunk)
        body = b"".join(chunks)

        preview = body[:4096] if body else None
        ctx = PrePersistContext(metadata=metadata, content_preview=preview)
        # May raise BlobRejectedError — propagates without write.
        await self.pre_persist_hook(ctx)

        key = self._build_key(metadata)
        await self._manager.create_file(key, body)

        blob_ref = self._to_ref(key)
        self.logger.info(
            "blob persisted: %s (%d bytes, %s)",
            blob_ref,
            metadata.size_bytes,
            metadata.content_type,
        )
        return blob_ref

    async def get(self, blob_ref: str) -> AsyncIterator[bytes]:
        key = self._from_ref(blob_ref)
        buf = BytesIO()
        await self._manager.download_file(key, buf)
        buf.seek(0)

        async def _iter() -> AsyncIterator[bytes]:
            while True:
                chunk = buf.read(_CHUNK_SIZE)
                if not chunk:
                    return
                yield chunk

        return _iter()

    async def delete(self, blob_ref: str) -> None:
        key = self._from_ref(blob_ref)
        try:
            await self._manager.delete_file(key)
            self.logger.debug("blob deleted: %s", blob_ref)
        except FileNotFoundError:
            # Idempotent: missing blob is not an error.
            return
        except Exception as exc:  # noqa: BLE001
            err_code = getattr(exc, "response", {}).get("Error", {}).get(
                "Code", ""
            )
            if err_code in ("NoSuchKey", "404"):
                return
            self.logger.warning(
                "blob delete failed (non-critical): %s — %s", blob_ref, exc
            )


# ---------------------------------------------------------------------------
# S3 backend
# ---------------------------------------------------------------------------


class S3BlobStorage(_ManagerBackedBlobStorage):
    """S3 blob storage backed by ``navigator.utils.file.s3.S3FileManager``.

    Credentials are resolved by ``S3FileManager`` using ``AWS_CREDENTIALS``
    from ``parrot.conf`` keyed by ``aws_id`` (default ``"default"``), or an
    explicit ``credentials`` dict passed through. Bucket resolution falls
    back to ``PARROT_BLOB_BUCKET`` for backward compatibility, then to the
    credential profile's ``bucket_name``.

    blob_ref format::

        s3://<bucket>/<prefix><form_id>/<field_id>/<uuid>

    Args:
        bucket: S3 bucket name. Falls back to ``PARROT_BLOB_BUCKET`` env var
            and then to ``AWS_CREDENTIALS[aws_id]["bucket_name"]``.
        prefix: Key prefix prepended to every blob. Falls back to
            ``PARROT_BLOB_PREFIX``. Defaults to ``""``.
        aws_id: Name of the profile in ``AWS_CREDENTIALS`` (default
            ``"default"``).
        region_name: AWS region override.
        credentials: Explicit credentials dict (``{"aws_key": ..., "aws_secret": ...}``).
            Bypasses ``AWS_CREDENTIALS`` lookup when provided.

    Raises:
        RuntimeError: If no bucket can be resolved.
    """

    scheme = "s3"

    def __init__(
        self,
        *,
        bucket: str | None = None,
        prefix: str = "",
        aws_id: str = "default",
        region_name: str | None = None,
        credentials: dict[str, Any] | None = None,
    ) -> None:
        super().__init__()
        from navigator.utils.file.s3 import S3FileManager  # deferred import

        resolved_bucket = bucket or os.environ.get("PARROT_BLOB_BUCKET") or None
        resolved_prefix = prefix or os.environ.get("PARROT_BLOB_PREFIX", "")
        self._prefix = (
            resolved_prefix.rstrip("/") + "/" if resolved_prefix else ""
        )

        manager = S3FileManager(
            bucket_name=resolved_bucket,
            aws_id=aws_id,
            region_name=region_name,
            prefix="",  # prefix is applied by _build_key; keep manager flat
            credentials=credentials,
        )
        if not manager.bucket_name:
            raise RuntimeError(
                "S3BlobStorage requires a bucket. Pass bucket=, set "
                "PARROT_BLOB_BUCKET, or set bucket_name in the "
                f"AWS_CREDENTIALS[{aws_id!r}] profile."
            )

        self._manager = manager
        self._bucket = manager.bucket_name

    # Backward-compatible attributes preserved for external callers/tests
    # that reach in for ``.bucket`` / ``.prefix``.
    @property
    def bucket(self) -> str:
        return self._bucket or ""

    @property
    def prefix(self) -> str:
        return self._prefix


# ---------------------------------------------------------------------------
# GCS backend
# ---------------------------------------------------------------------------


class GCSBlobStorage(_ManagerBackedBlobStorage):
    """GCS blob storage backed by ``navigator.utils.file.gcs.GCSFileManager``.

    blob_ref format::

        gs://<bucket>/<prefix><form_id>/<field_id>/<uuid>

    Args:
        bucket: GCS bucket name.
        prefix: Key prefix prepended to every blob.
        **manager_kwargs: Forwarded to ``GCSFileManager`` (e.g.
            ``project_id``, ``credentials_path``).

    Raises:
        RuntimeError: If no bucket is provided.
    """

    scheme = "gs"

    def __init__(
        self,
        *,
        bucket: str | None = None,
        prefix: str = "",
        **manager_kwargs: Any,
    ) -> None:
        super().__init__()
        from navigator.utils.file.gcs import GCSFileManager  # deferred import

        resolved_bucket = bucket or os.environ.get("PARROT_BLOB_BUCKET") or None
        if not resolved_bucket:
            raise RuntimeError(
                "GCSBlobStorage requires a bucket. "
                "Pass bucket= or set PARROT_BLOB_BUCKET."
            )

        resolved_prefix = prefix or os.environ.get("PARROT_BLOB_PREFIX", "")
        self._prefix = (
            resolved_prefix.rstrip("/") + "/" if resolved_prefix else ""
        )

        self._manager = GCSFileManager(
            bucket_name=resolved_bucket,
            prefix="",
            **manager_kwargs,
        )
        self._bucket = resolved_bucket


# ---------------------------------------------------------------------------
# Local filesystem backend
# ---------------------------------------------------------------------------


class LocalBlobStorage(_ManagerBackedBlobStorage):
    """Local filesystem blob storage backed by ``LocalFileManager``.

    Suitable for single-host deployments or development environments. All
    blobs live under a single ``base_path`` directory sandboxed by the
    underlying ``LocalFileManager``.

    blob_ref format::

        file://<prefix><form_id>/<field_id>/<uuid>

    The path is relative to the manager's ``base_path`` — refs are only
    valid against the same ``LocalBlobStorage`` configuration that produced
    them.

    Args:
        base_path: Root directory for blob storage. Falls back to
            ``PARROT_BLOB_PATH`` env var, then to ``"./blobs"``.
        prefix: Key prefix prepended to every blob.
    """

    scheme = "file"

    def __init__(
        self,
        *,
        base_path: str | Path | None = None,
        prefix: str = "",
    ) -> None:
        super().__init__()
        from navigator.utils.file.local import LocalFileManager  # deferred

        resolved_base = (
            base_path
            or os.environ.get("PARROT_BLOB_PATH")
            or "./blobs"
        )
        resolved_prefix = prefix or os.environ.get("PARROT_BLOB_PREFIX", "")
        self._prefix = (
            resolved_prefix.rstrip("/") + "/" if resolved_prefix else ""
        )

        self._manager = LocalFileManager(base_path=resolved_base)
        self._bucket = None


# ---------------------------------------------------------------------------
# Temp filesystem backend (testing / lazy default)
# ---------------------------------------------------------------------------


class TempBlobStorage(_ManagerBackedBlobStorage):
    """Ephemeral blob storage backed by ``TempFileManager``.

    Default lazy backend when no ``app["blob_storage"]`` is configured.
    Useful for tests and local development: never talks to S3/GCS, never
    needs credentials, and cleans itself up on process exit.

    blob_ref format::

        temp://<prefix><form_id>/<field_id>/<uuid>

    Args:
        prefix: Key prefix prepended to every blob (also passed as the
            temp-directory prefix when ``temp_dir_prefix`` is omitted).
        temp_dir_prefix: Override the temp-directory name prefix.
    """

    scheme = "temp"

    def __init__(
        self,
        *,
        prefix: str = "",
        temp_dir_prefix: str = "parrot_blobs_",
    ) -> None:
        super().__init__()
        from navigator.utils.file.tmp import TempFileManager  # deferred

        resolved_prefix = prefix or os.environ.get("PARROT_BLOB_PREFIX", "")
        self._prefix = (
            resolved_prefix.rstrip("/") + "/" if resolved_prefix else ""
        )

        self._manager = TempFileManager(prefix=temp_dir_prefix)
        self._bucket = None

    async def get(self, blob_ref: str) -> AsyncIterator[bytes]:
        """Stream the blob bytes directly from disk.

        ``TempFileManager.download_file`` has *move* semantics — it removes
        the source after copying — so we read the file via ``Path`` instead
        to keep ``get()`` idempotent.
        """
        key = self._from_ref(blob_ref)
        path: Path = self._manager._resolve_path(key)  # type: ignore[attr-defined]
        data = await _read_bytes(path)

        async def _iter() -> AsyncIterator[bytes]:
            offset = 0
            while offset < len(data):
                yield data[offset: offset + _CHUNK_SIZE]
                offset += _CHUNK_SIZE

        return _iter()


async def _read_bytes(path: Path) -> bytes:
    """Read ``path`` into memory off the event loop."""
    import asyncio

    return await asyncio.to_thread(path.read_bytes)


__all__ = (
    "AbstractBlobStorage",
    "BlobMetadata",
    "BlobRejectedError",
    "GCSBlobStorage",
    "LocalBlobStorage",
    "PrePersistContext",
    "S3BlobStorage",
    "TempBlobStorage",
)
