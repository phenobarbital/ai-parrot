"""Async blob storage abstraction for FieldType.REST file uploads."""

from __future__ import annotations

import contextlib
import logging
import os
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

# S3 minimum part size for multipart upload (5 MB)
_MIN_PART_BYTES = 5 * 1024 * 1024


class BlobMetadata(BaseModel):
    """Metadata attached to every blob upload."""

    model_config = ConfigDict(extra="forbid")

    form_id: str
    field_id: str
    submission_id: str | None = None
    tenant: str | None = None
    content_type: str
    size_bytes: int


class PrePersistContext(BaseModel):
    """Context passed to pre_persist_hook before a blob is written."""

    model_config = ConfigDict(extra="forbid")

    metadata: BlobMetadata
    content_preview: bytes | None = None


class BlobRejectedError(Exception):
    """Raised by pre_persist_hook to abort a put without writing to storage."""


class AbstractBlobStorage(ABC):
    """Abstract interface for async binary blob storage.

    Subclasses must implement put/get/delete. Override pre_persist_hook
    to add validation or scanning logic before each upload.
    """

    @abstractmethod
    async def put(
        self,
        data: AsyncIterator[bytes],
        *,
        metadata: BlobMetadata,
    ) -> str:
        """Upload a blob and return its reference URI.

        Args:
            data: Async iterator of byte chunks.
            metadata: Metadata describing the blob.

        Returns:
            A URI string identifying the stored blob.

        Raises:
            BlobRejectedError: If pre_persist_hook rejects the blob.
        """

    @abstractmethod
    async def get(self, blob_ref: str) -> AsyncIterator[bytes]:
        """Download a blob as an async stream.

        Args:
            blob_ref: URI returned by put().

        Returns:
            Async iterator of byte chunks.
        """

    @abstractmethod
    async def delete(self, blob_ref: str) -> None:
        """Delete a blob. Idempotent — absent key must not raise.

        Args:
            blob_ref: URI returned by put().
        """

    async def pre_persist_hook(self, ctx: PrePersistContext) -> None:
        """Called before each put. Default is a no-op.

        Args:
            ctx: Upload context with metadata and optional content preview.

        Raises:
            BlobRejectedError: To abort the upload without writing.
        """
        return None


class S3BlobStorage(AbstractBlobStorage):
    """AWS S3-backed blob storage using aioboto3 with streaming multipart upload.

    Blob references use the format:
        s3://<bucket>/<prefix><form_id>/<field_id>/<uuid>

    Args:
        bucket: S3 bucket name. Falls back to PARROT_BLOB_BUCKET env var.
        prefix: Key prefix. Falls back to PARROT_BLOB_PREFIX env var.
        endpoint_url: S3-compatible endpoint URL. Falls back to
            PARROT_BLOB_ENDPOINT_URL env var.
    """

    def __init__(
        self,
        bucket: str | None = None,
        prefix: str | None = None,
        endpoint_url: str | None = None,
    ) -> None:
        self._bucket = bucket or os.environ.get("PARROT_BLOB_BUCKET", "")
        self._prefix = prefix or os.environ.get("PARROT_BLOB_PREFIX", "")
        self._endpoint_url = endpoint_url or os.environ.get("PARROT_BLOB_ENDPOINT_URL")
        self.logger = logging.getLogger(__name__)

    def _build_key(self, metadata: BlobMetadata) -> str:
        prefix = self._prefix.rstrip("/") + "/" if self._prefix else ""
        return f"{prefix}{metadata.form_id}/{metadata.field_id}/{uuid.uuid4()}"

    def _parse_ref(self, blob_ref: str) -> tuple[str, str]:
        without_scheme = blob_ref.removeprefix("s3://")
        bucket, _, key = without_scheme.partition("/")
        return bucket, key

    def _client_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if self._endpoint_url:
            kwargs["endpoint_url"] = self._endpoint_url
        return kwargs

    async def put(
        self,
        data: AsyncIterator[bytes],
        *,
        metadata: BlobMetadata,
    ) -> str:
        """Upload a blob via S3 multipart upload (stream-friendly).

        Calls pre_persist_hook before opening the S3 connection. If the hook
        raises BlobRejectedError, no bytes are written to S3.

        Args:
            data: Async iterator of byte chunks. Not fully buffered in memory.
            metadata: Blob metadata including content_type.

        Returns:
            s3://<bucket>/<key> reference URI.

        Raises:
            BlobRejectedError: If pre_persist_hook rejects the upload.
        """
        import aioboto3  # noqa: PLC0415 — deferred; aioboto3 added by TASK-1169

        ctx = PrePersistContext(metadata=metadata)
        await self.pre_persist_hook(ctx)

        key = self._build_key(metadata)
        session = aioboto3.Session()

        async with session.client("s3", **self._client_kwargs()) as s3:
            mpu = await s3.create_multipart_upload(
                Bucket=self._bucket,
                Key=key,
                ContentType=metadata.content_type,
            )
            upload_id: str = mpu["UploadId"]
            parts: list[dict[str, Any]] = []
            part_number = 1
            buffer = bytearray()

            try:
                async for chunk in data:
                    buffer.extend(chunk)
                    while len(buffer) >= _MIN_PART_BYTES:
                        part_body = bytes(buffer[:_MIN_PART_BYTES])
                        del buffer[:_MIN_PART_BYTES]
                        resp = await s3.upload_part(
                            Bucket=self._bucket,
                            Key=key,
                            UploadId=upload_id,
                            PartNumber=part_number,
                            Body=part_body,
                        )
                        parts.append({"PartNumber": part_number, "ETag": resp["ETag"]})
                        part_number += 1

                # Upload remaining bytes (always required if no full parts yet)
                if buffer or not parts:
                    resp = await s3.upload_part(
                        Bucket=self._bucket,
                        Key=key,
                        UploadId=upload_id,
                        PartNumber=part_number,
                        Body=bytes(buffer),
                    )
                    parts.append({"PartNumber": part_number, "ETag": resp["ETag"]})

                await s3.complete_multipart_upload(
                    Bucket=self._bucket,
                    Key=key,
                    UploadId=upload_id,
                    MultipartUpload={"Parts": parts},
                )
            except Exception:
                with contextlib.suppress(Exception):
                    await s3.abort_multipart_upload(
                        Bucket=self._bucket, Key=key, UploadId=upload_id
                    )
                raise

        blob_ref = f"s3://{self._bucket}/{key}"
        self.logger.debug("Stored blob at %s", blob_ref)
        return blob_ref

    async def get(self, blob_ref: str) -> AsyncIterator[bytes]:  # type: ignore[override]
        """Download a blob from S3 as a streaming async iterator.

        Args:
            blob_ref: s3:// URI returned by put().

        Returns:
            Async iterator of byte chunks.
        """
        import aioboto3  # noqa: PLC0415

        bucket, key = self._parse_ref(blob_ref)
        session = aioboto3.Session()

        async with session.client("s3", **self._client_kwargs()) as s3:
            resp = await s3.get_object(Bucket=bucket, Key=key)
            async for chunk in resp["Body"].iter_chunks():
                yield chunk

    async def delete(self, blob_ref: str) -> None:
        """Delete a blob from S3. Idempotent — S3 delete_object never raises on missing keys.

        Args:
            blob_ref: s3:// URI returned by put().
        """
        import aioboto3  # noqa: PLC0415

        bucket, key = self._parse_ref(blob_ref)
        session = aioboto3.Session()

        async with session.client("s3", **self._client_kwargs()) as s3:
            await s3.delete_object(Bucket=bucket, Key=key)

        self.logger.debug("Deleted blob %s", blob_ref)
