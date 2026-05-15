"""Async blob storage abstraction for FieldType.REST uploads.

Provides ``AbstractBlobStorage`` (ABC) and a default ``S3BlobStorage``
implementation using ``aioboto3``. The ``pre_persist_hook`` is a V1 stub
(no-op by default); V2 will wire AV/content-scanning here.

Bucket, prefix, and endpoint URL are configurable via constructor args
or environment variables (``PARROT_BLOB_BUCKET``, ``PARROT_BLOB_PREFIX``,
``PARROT_BLOB_ENDPOINT_URL``).

This module has no callers in V1 other than ``api/uploads.py`` (TASK-1170).
Auth is the handler's concern, not the storage layer's.
"""

from __future__ import annotations

import logging
import os
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
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

    Concrete implementations: ``S3BlobStorage`` (default), and any
    user-supplied backend (GCS, local FS, etc.) inheriting from this class.

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

        The stream is consumed from the async iterator. The V1 default
        ``S3BlobStorage`` implementation collects all chunks before
        uploading (single ``put_object`` call); future revisions will
        use multipart streaming for large blobs. The returned reference
        format is implementation-defined
        (e.g. ``s3://bucket/prefix/form/field/uuid``).

        The ``pre_persist_hook`` is invoked before writing begins; if it
        raises ``BlobRejectedError`` the blob is NOT written and the error
        propagates to the caller.

        Args:
            stream: Async byte-chunk iterator (never buffered entirely).
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
# S3 implementation
# ---------------------------------------------------------------------------


class S3BlobStorage(AbstractBlobStorage):
    """Default blob storage implementation using ``aioboto3`` (async S3).

    Bucket, prefix, and endpoint URL are resolved in this order:
    1. Constructor keyword arguments.
    2. Environment variables (``PARROT_BLOB_BUCKET``, ``PARROT_BLOB_PREFIX``,
       ``PARROT_BLOB_ENDPOINT_URL``).
    3. Defaults (empty prefix; endpoint defaults to AWS).

    The returned ``blob_ref`` format is::

        s3://<bucket>/<prefix><form_id>/<field_id>/<uuid>

    Args:
        bucket: S3 bucket name. Falls back to ``PARROT_BLOB_BUCKET`` env var.
        prefix: Key prefix (e.g. ``"forms/"``). Falls back to
            ``PARROT_BLOB_PREFIX`` env var. Defaults to ``""``.
        endpoint_url: Custom S3-compatible endpoint URL. Falls back to
            ``PARROT_BLOB_ENDPOINT_URL`` env var.

    Raises:
        RuntimeError: On construction if no bucket is resolvable.
    """

    def __init__(
        self,
        *,
        bucket: str | None = None,
        prefix: str = "",
        endpoint_url: str | None = None,
    ) -> None:
        self.logger = logging.getLogger(__name__)
        self.bucket: str = bucket or os.environ.get("PARROT_BLOB_BUCKET", "")
        self.prefix: str = prefix or os.environ.get("PARROT_BLOB_PREFIX", "")
        self.endpoint_url: str | None = endpoint_url or os.environ.get(
            "PARROT_BLOB_ENDPOINT_URL"
        )
        if not self.bucket:
            raise RuntimeError(
                "S3BlobStorage requires a bucket. "
                "Pass bucket= or set PARROT_BLOB_BUCKET."
            )

    def _build_key(self, metadata: BlobMetadata) -> str:
        """Build the S3 object key for a blob.

        Args:
            metadata: Blob metadata.

        Returns:
            S3 object key string.
        """
        blob_id = str(uuid.uuid4())
        return f"{self.prefix}{metadata.form_id}/{metadata.field_id}/{blob_id}"

    def _parse_ref(self, blob_ref: str) -> str:
        """Extract the S3 key from a ``blob_ref``.

        Args:
            blob_ref: Full blob reference (``s3://bucket/key``).

        Returns:
            S3 object key (path after the bucket name).
        """
        # blob_ref is "s3://bucket/key"
        without_scheme = blob_ref[len("s3://"):]
        # split on first "/" to separate bucket from key
        _, key = without_scheme.split("/", 1)
        return key

    async def put(
        self,
        stream: AsyncIterator[bytes],
        *,
        metadata: BlobMetadata,
    ) -> str:
        """Persist a blob to S3 and return a stable blob reference.

        Streams content incrementally via ``put_object`` (collected into a
        single multipart body to satisfy the aioboto3 API while still
        supporting streaming input). Large uploads should use multipart in
        a future revision; V1 collects and uploads in one call.

        The ``pre_persist_hook`` is invoked before writing. If it raises
        ``BlobRejectedError`` the blob is NOT written.

        Args:
            stream: Async byte-chunk iterator.
            metadata: Contextual metadata for the blob.

        Returns:
            Blob reference string (``s3://bucket/key``).

        Raises:
            BlobRejectedError: If ``pre_persist_hook`` rejects the blob.
        """
        import aioboto3  # deferred import — added by TASK-1169

        # Collect stream chunks (V1: single-request upload)
        chunks: list[bytes] = []
        async for chunk in stream:
            chunks.append(chunk)
        body = b"".join(chunks)

        # Pre-persist hook (stub in V1 — no-op by default)
        preview = body[:4096] if body else None
        ctx = PrePersistContext(
            metadata=metadata,
            content_preview=preview,
        )
        # May raise BlobRejectedError — propagates without write
        await self.pre_persist_hook(ctx)

        key = self._build_key(metadata)

        session = aioboto3.Session()
        client_kwargs: dict[str, Any] = {}
        if self.endpoint_url:
            client_kwargs["endpoint_url"] = self.endpoint_url

        async with session.client("s3", **client_kwargs) as s3:
            await s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=body,
                ContentType=metadata.content_type,
            )

        blob_ref = f"s3://{self.bucket}/{key}"
        self.logger.info(
            "blob persisted: %s (%d bytes, %s)",
            blob_ref,
            metadata.size_bytes,
            metadata.content_type,
        )
        return blob_ref

    async def get(self, blob_ref: str) -> AsyncIterator[bytes]:
        """Stream a blob from S3 by reference.

        Args:
            blob_ref: Blob reference returned by ``put``.

        Returns:
            Async iterator of byte chunks.
        """
        import aioboto3  # deferred import

        key = self._parse_ref(blob_ref)
        client_kwargs: dict[str, Any] = {}
        if self.endpoint_url:
            client_kwargs["endpoint_url"] = self.endpoint_url

        session = aioboto3.Session()
        async with session.client("s3", **client_kwargs) as s3:
            response = await s3.get_object(Bucket=self.bucket, Key=key)
            async for chunk in response["Body"].iter_chunks():
                yield chunk

    async def delete(self, blob_ref: str) -> None:
        """Delete a blob from S3. Idempotent — no error if the key is missing.

        Args:
            blob_ref: Blob reference returned by ``put``.
        """
        import aioboto3  # deferred import

        key = self._parse_ref(blob_ref)
        client_kwargs: dict[str, Any] = {}
        if self.endpoint_url:
            client_kwargs["endpoint_url"] = self.endpoint_url

        session = aioboto3.Session()
        async with session.client("s3", **client_kwargs) as s3:
            try:
                await s3.delete_object(Bucket=self.bucket, Key=key)
                self.logger.debug("blob deleted: %s", blob_ref)
            except Exception as exc:  # noqa: BLE001
                # S3 delete_object does not raise for missing keys, but
                # guard against any implementation variation.
                err_code = getattr(exc, "response", {}).get("Error", {}).get(
                    "Code", ""
                )
                if err_code not in ("NoSuchKey", "404"):
                    self.logger.warning(
                        "blob delete failed (non-critical): %s — %s",
                        blob_ref,
                        exc,
                    )
