"""Squawk blob storage over the duck-typed file manager used by artifact storage."""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from cryptography.fernet import Fernet

from parrot.interagent import HandleClaimError, HandleOwner, MediaType, SquawkError, SquawkErrorCode
from parrot.squawk.blobs.store import BlobMeta, SquawkBlobStore, _authorize

CHUNK = 1024 * 1024
_KEY_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class FileManagerBlobStore(SquawkBlobStore):
    """Store blobs using only the six file-manager methods in the duck contract.

    The upstream file manager has no byte-range download operation. Reads therefore
    download the complete object, decrypt it when needed, and then yield the requested
    plaintext slice.
    """

    def __init__(
        self,
        file_manager: Any,
        *,
        prefix: str = "squawk/blobs",
        encrypt_classes: frozenset[str] = frozenset({"hr", "pii"}),
        key_env: str = "SQUAWK_BLOB_KEY",
    ) -> None:
        """Initialize file-manager-backed blob storage.

        Args:
            file_manager: Object implementing the six-method file-manager duck contract.
            prefix: Object-name prefix reserved for Squawk blobs.
            encrypt_classes: Data classes encrypted before publication.
            key_env: Environment variable containing the Fernet key.

        Raises:
            SquawkError: If encryption is configured without a key.
        """
        self._fm = file_manager
        self._prefix = prefix.strip("/")
        self._encrypt = encrypt_classes
        key = os.environ.get(key_env)
        if encrypt_classes and not key:
            raise SquawkError(SquawkErrorCode.UPSTREAM_FAILED, "no_blob_key")
        self._fernet = Fernet(key.encode()) if key else None
        self.logger = logging.getLogger(__name__)

    def _names(self, key: str) -> tuple[str, str]:
        """Return binary and metadata object names for a content key.

        Args:
            key: SHA-256-prefixed blob key.

        Returns:
            Binary and metadata object names.

        Raises:
            HandleClaimError: If the key is malformed.
        """
        if not _KEY_RE.fullmatch(key):
            raise HandleClaimError()
        hex_digest = key.split(":", 1)[1]
        base = f"{self._prefix}/{hex_digest[:2]}/{hex_digest}"
        return f"{base}.bin", f"{base}.meta.json"

    async def _download(self, name: str) -> bytes:
        """Download a complete object into memory.

        Args:
            name: File-manager object name.

        Returns:
            Downloaded object bytes.
        """
        buffer = io.BytesIO()
        await self._fm.download_file(name, buffer)
        return buffer.getvalue()

    async def _publish_binary(self, name: str, payload: bytes) -> None:
        """Upload and verify a binary object before metadata publication.

        Args:
            name: Destination object name.
            payload: Exact bytes to upload.

        Raises:
            SquawkError: If the manager declines or cannot verify the upload.
        """
        written = await self._fm.create_from_bytes(name, payload)
        if written is False or not await self._exists(name):
            raise SquawkError(SquawkErrorCode.UPSTREAM_FAILED, "blob_publish_failed")
        file_metadata = await self._fm.get_file_metadata(name)
        size = getattr(file_metadata, "size", None)
        if size is None or int(size) != len(payload):
            raise SquawkError(SquawkErrorCode.UPSTREAM_FAILED, "blob_size_mismatch")

    async def put_stream(
        self,
        frames: AsyncIterator[bytes],
        *,
        media_type: MediaType,
        owner: HandleOwner,
        ttl_s: int,
        expected_digest: str | None = None,
        data_class: str = "internal",
    ) -> BlobMeta:
        """Hash plaintext frames and publish the binary before its metadata.

        Args:
            frames: Plaintext byte chunks.
            media_type: Artifact media type.
            owner: Owner tuple authorized for the blob.
            ttl_s: Lifetime in seconds.
            expected_digest: Optional expected ``sha256:<hex>`` key.
            data_class: Policy class controlling encryption at rest.

        Returns:
            Published or deduplicated metadata.

        Raises:
            SquawkError: If the digest differs or publication cannot be verified.
        """
        digest = hashlib.sha256()
        byte_size = 0
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_path = Path(temp_file.name)
            async for chunk in frames:
                digest.update(chunk)
                await asyncio.to_thread(temp_file.write, chunk)
                byte_size += len(chunk)

        try:
            key = f"sha256:{digest.hexdigest()}"
            if expected_digest is not None and expected_digest != key:
                raise SquawkError(SquawkErrorCode.UPSTREAM_FAILED, "digest_mismatch")

            bin_name, meta_name = self._names(key)
            if await self._exists(meta_name):
                existing = await self.meta(key)
                if existing is not None:
                    return existing

            payload = await asyncio.to_thread(temp_path.read_bytes)
            encrypted = data_class in self._encrypt
            if encrypted:
                if self._fernet is None:
                    raise SquawkError(SquawkErrorCode.UPSTREAM_FAILED, "no_blob_key")
                payload = await asyncio.to_thread(self._fernet.encrypt, payload)

            try:
                await self._publish_binary(bin_name, payload)
            except Exception:
                try:
                    await self._fm.delete_file(bin_name)
                except Exception:  # noqa: BLE001 - cleanup must not mask publication failure
                    self.logger.warning("Could not clean up unverified blob %s", bin_name)
                raise

            now = datetime.now(timezone.utc)
            metadata = BlobMeta(
                key=key,
                media_type=media_type,
                byte_size=byte_size,
                created_at=now,
                expires_at=now + timedelta(seconds=ttl_s),
                owner=owner,
                encrypted=encrypted,
                data_class=data_class,
            )
            written = await self._fm.create_from_bytes(meta_name, metadata.model_dump_json().encode())
            if written is False:
                raise SquawkError(SquawkErrorCode.UPSTREAM_FAILED, "metadata_publish_failed")
            return metadata
        finally:
            await asyncio.to_thread(temp_path.unlink, missing_ok=True)

    async def _exists(self, name: str) -> bool:
        """Return whether a file-manager object exists.

        Args:
            name: File-manager object name.

        Returns:
            Whether the object exists.
        """
        return bool(await self._fm.exists(name))

    async def has(self, key: str) -> bool:
        """Return whether metadata exists for a blob key.

        Args:
            key: Content-addressed blob key.

        Returns:
            Whether metadata exists.
        """
        return await self._exists(self._names(key)[1])

    async def meta(self, key: str) -> BlobMeta | None:
        """Load metadata for a blob key.

        Args:
            key: Content-addressed blob key.

        Returns:
            Parsed metadata, or ``None`` when absent.
        """
        meta_name = self._names(key)[1]
        if not await self._exists(meta_name):
            return None
        return BlobMeta.model_validate_json(await self._download(meta_name))

    async def open_read(
        self,
        key: str,
        *,
        owner: HandleOwner,
        grantee: str | None = None,
        offset: int = 0,
        length: int | None = None,
    ) -> AsyncIterator[bytes]:
        """Download the object and yield an authorized plaintext byte range.

        Args:
            key: Content-addressed blob key.
            owner: Full owner tuple asserted by the caller.
            grantee: Agent identity used for explicit grant access.
            offset: First plaintext byte to return.
            length: Maximum plaintext bytes to return, or all remaining bytes.

        Yields:
            Plaintext chunks no larger than :data:`CHUNK`.

        Raises:
            HandleClaimError: If the blob is missing, expired, or unauthorized.
            ValueError: If the range bounds are negative.
        """
        if offset < 0 or (length is not None and length < 0):
            raise ValueError("offset and length must be non-negative")
        metadata = await self.meta(key)
        if metadata is None:
            raise HandleClaimError()
        _authorize(metadata, owner, grantee)

        payload = await self._download(self._names(key)[0])
        if metadata.encrypted:
            if self._fernet is None:
                raise SquawkError(SquawkErrorCode.UPSTREAM_FAILED, "no_blob_key")
            payload = await asyncio.to_thread(self._fernet.decrypt, payload)
        end = None if length is None else offset + length
        selected = payload[offset:end]
        for position in range(0, len(selected), CHUNK):
            yield selected[position : position + CHUNK]

    async def grant(self, key: str, *, owner: HandleOwner, grantee: str) -> BlobMeta:
        """Grant read access when requested by the blob owner.

        Args:
            key: Content-addressed blob key.
            owner: Full owner tuple asserted by the caller.
            grantee: Agent identity to authorize.

        Returns:
            Updated metadata.

        Raises:
            HandleClaimError: If the blob is missing or the caller is not its owner.
        """
        metadata = await self.meta(key)
        if metadata is None or metadata.owner != owner:
            raise HandleClaimError()
        updated = metadata.model_copy(update={"grants": (*metadata.grants, grantee)})
        written = await self._fm.create_from_bytes(self._names(key)[1], updated.model_dump_json().encode())
        if written is False:
            raise SquawkError(SquawkErrorCode.UPSTREAM_FAILED, "metadata_publish_failed")
        return updated

    async def delete(self, key: str, *, owner: HandleOwner) -> bool:
        """Delete an object pair when requested by its owner.

        Args:
            key: Content-addressed blob key.
            owner: Full owner tuple asserted by the caller.

        Returns:
            Whether the blob existed.

        Raises:
            HandleClaimError: If the caller is not the blob owner.
        """
        metadata = await self.meta(key)
        if metadata is None:
            return False
        if metadata.owner != owner:
            raise HandleClaimError()
        bin_name, meta_name = self._names(key)
        await self._fm.delete_file(bin_name)
        await self._fm.delete_file(meta_name)
        return True

    async def sweep(self, now: datetime | None = None) -> int:
        """Delete every object pair expired at the supplied cutoff.

        Args:
            now: Optional expiry cutoff, defaulting to current UTC time.

        Returns:
            Number of expired metadata records removed.
        """
        cutoff = now or datetime.now(timezone.utc)
        found = await self._fm.find_files(prefix=self._prefix)
        removed = 0
        for file_metadata in found or ():
            meta_name = str(getattr(file_metadata, "path", ""))
            if not meta_name.endswith(".meta.json"):
                continue
            metadata = BlobMeta.model_validate_json(await self._download(meta_name))
            if metadata.expires_at > cutoff:
                continue
            bin_name = meta_name.removesuffix(".meta.json") + ".bin"
            await self._fm.delete_file(bin_name)
            await self._fm.delete_file(meta_name)
            removed += 1
        return removed
