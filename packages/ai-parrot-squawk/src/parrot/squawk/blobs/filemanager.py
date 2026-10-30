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
from parrot.squawk.blobs.store import BlobMeta, SquawkBlobStore, owner_slug, select_record

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
        orphan_grace_s: int = 3600,
        max_bytes: int = 1024 * 1024 * 1024,
    ) -> None:
        """Initialize file-manager-backed blob storage.

        Args:
            file_manager: Object implementing the six-method file-manager duck contract.
            prefix: Object-name prefix reserved for Squawk blobs.
            encrypt_classes: Data classes encrypted before publication.
            key_env: Environment variable containing the Fernet key.
            max_bytes: Largest plaintext object accepted by ``put_stream`` (default 1 GiB).
            orphan_grace_s: Age after which a ``.bin`` without metadata is swept (when
                the manager reports a modification time).

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
        self._orphan_grace_s = orphan_grace_s
        self._max_bytes = max_bytes
        self._meta_lock = asyncio.Lock()
        self.logger = logging.getLogger(__name__)

    def _base(self, key: str) -> str:
        """Return the object-name prefix holding every owner record for a key.

        Args:
            key: SHA-256-prefixed blob key.

        Returns:
            The per-key prefix (no trailing slash).

        Raises:
            HandleClaimError: If the key is malformed.
        """
        if not _KEY_RE.fullmatch(key):
            raise HandleClaimError()
        hex_digest = key.split(":", 1)[1]
        return f"{self._prefix}/{hex_digest[:2]}/{hex_digest}"

    def _names(self, key: str, owner: HandleOwner) -> tuple[str, str]:
        """Return binary and metadata object names for one owner's record of a key.

        Args:
            key: SHA-256-prefixed blob key.
            owner: Owner tuple.

        Returns:
            Binary and metadata object names.
        """
        base = f"{self._base(key)}/{owner_slug(owner)}"
        return f"{base}.bin", f"{base}.meta.json"

    async def _read_meta(self, name: str) -> BlobMeta | None:
        """Download and parse one metadata object, tolerating corruption and races.

        Args:
            name: Metadata object name.

        Returns:
            Parsed metadata, or ``None`` when missing or unparseable.
        """
        try:
            if not await self._exists(name):
                return None
            return BlobMeta.model_validate_json(await self._download(name))
        except Exception:  # noqa: BLE001 - one corrupt or vanished record must not stall reads or sweeps
            self.logger.warning("FileManagerBlobStore: unreadable metadata %s", name, exc_info=True)
            return None

    async def _write_meta(self, name: str, metadata: BlobMeta) -> None:
        """Publish a metadata object in a single ``create_from_bytes`` call.

        Args:
            name: Metadata object name.
            metadata: Record to persist.

        Raises:
            SquawkError: If the manager declines the write.
        """
        written = await self._fm.create_from_bytes(name, metadata.model_dump_json().encode())
        if written is False:
            raise SquawkError(SquawkErrorCode.UPSTREAM_FAILED, "metadata_publish_failed")

    async def _records(self, key: str) -> list[BlobMeta]:
        """Load every readable owner record stored for a key.

        Args:
            key: SHA-256-prefixed blob key.

        Returns:
            Parsed records.
        """
        found = await self._fm.find_files(prefix=self._base(key) + "/")
        records: list[BlobMeta] = []
        for file_metadata in found or ():
            name = str(getattr(file_metadata, "path", ""))
            if name.endswith(".meta.json"):
                meta = await self._read_meta(name)
                if meta is not None:
                    records.append(meta)
        return records

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
        """Hash plaintext frames and publish the binary before its metadata, for ``owner``.

        Dedup is per owner: an unexpired record of the same owner and data class
        is reused (expiry extended to the later of the two); otherwise the record
        is republished. Other owners' records are never returned or modified.
        The duck contract only uploads from ``bytes``, so the staged object is
        read into memory once for upload.

        Args:
            frames: Plaintext byte chunks.
            media_type: Artifact media type.
            owner: Owner tuple authorized for the blob.
            ttl_s: Lifetime in seconds.
            expected_digest: Optional expected ``sha256:<hex>`` key.
            data_class: Policy class controlling encryption at rest.

        Returns:
            Published or deduplicated metadata owned by ``owner``.

        Raises:
            SquawkError: If the digest differs or publication cannot be verified.
        """
        digest = hashlib.sha256()
        byte_size = 0
        # mkstemp creates the file atomically with mode 0600 (O_EXCL): plaintext of an
        # hr/pii blob is staged unreadable to other users before it is encrypted.
        fd, temp_name = await asyncio.to_thread(tempfile.mkstemp, prefix="squawk-", suffix=".part")
        temp_path = Path(temp_name)
        temp_file = await asyncio.to_thread(os.fdopen, fd, "wb")
        try:
            try:
                async for chunk in frames:
                    digest.update(chunk)
                    await asyncio.to_thread(temp_file.write, chunk)
                    byte_size += len(chunk)
                    if byte_size > self._max_bytes:
                        raise SquawkError(SquawkErrorCode.UPSTREAM_FAILED, "blob_too_large")
            finally:
                await asyncio.to_thread(temp_file.close)

            key = f"sha256:{digest.hexdigest()}"
            if expected_digest is not None and expected_digest != key:
                raise SquawkError(SquawkErrorCode.UPSTREAM_FAILED, "digest_mismatch")

            bin_name, meta_name = self._names(key, owner)
            now = datetime.now(timezone.utc)
            new_expiry = now + timedelta(seconds=ttl_s)
            encrypted = data_class in self._encrypt
            async with self._meta_lock:
                existing = await self._read_meta(meta_name)
                if (
                    existing is not None
                    and existing.expires_at > now
                    and existing.data_class == data_class
                    and existing.encrypted == encrypted
                    and await self._exists(bin_name)
                ):
                    if new_expiry > existing.expires_at:
                        existing = existing.model_copy(update={"expires_at": new_expiry})
                        await self._write_meta(meta_name, existing)
                    return existing

                payload = await asyncio.to_thread(temp_path.read_bytes)
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

                metadata = BlobMeta(
                    key=key,
                    media_type=media_type,
                    byte_size=byte_size,
                    created_at=now,
                    expires_at=new_expiry,
                    owner=owner,
                    encrypted=encrypted,
                    data_class=data_class,
                )
                await self._write_meta(meta_name, metadata)
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

    async def has(self, key: str, *, owner: HandleOwner | None = None) -> bool:
        """Return whether an unexpired record exists for the key.

        Args:
            key: Content-addressed blob key.
            owner: Restrict the check to this owner's record when given.

        Returns:
            Whether a usable (unexpired) record exists.
        """
        meta = await self.meta(key, owner=owner)
        return meta is not None and meta.expires_at > datetime.now(timezone.utc)

    async def meta(self, key: str, *, owner: HandleOwner | None = None) -> BlobMeta | None:
        """Load a record for a blob key.

        Args:
            key: Content-addressed blob key.
            owner: Return this owner's record (expired or not); when ``None``,
                return any unexpired record.

        Returns:
            Parsed metadata, or ``None`` when absent.
        """
        if owner is not None:
            return await self._read_meta(self._names(key, owner)[1])
        now = datetime.now(timezone.utc)
        return next((m for m in await self._records(key) if m.expires_at > now), None)

    async def open_read(
        self,
        key: str,
        *,
        owner: HandleOwner,
        grantee: str | None = None,
        offset: int = 0,
        length: int | None = None,
    ) -> AsyncIterator[bytes]:
        """Download the authorized record's object and yield a plaintext byte range.

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
        metadata = select_record(await self._records(key), owner, grantee)
        bin_name = self._names(key, metadata.owner)[0]
        if not await self._exists(bin_name):
            raise HandleClaimError()
        payload = await self._download(bin_name)
        if metadata.encrypted:
            if self._fernet is None:
                raise SquawkError(SquawkErrorCode.UPSTREAM_FAILED, "no_blob_key")
            payload = await asyncio.to_thread(self._fernet.decrypt, payload)
        end = None if length is None else offset + length
        selected = payload[offset:end]
        for position in range(0, len(selected), CHUNK):
            yield selected[position : position + CHUNK]

    async def grant(self, key: str, *, owner: HandleOwner, grantee: str) -> BlobMeta:
        """Grant read access on the caller's own record (idempotent).

        Args:
            key: Content-addressed blob key.
            owner: Full owner tuple asserted by the caller.
            grantee: Agent identity to authorize.

        Returns:
            Updated metadata.

        Raises:
            HandleClaimError: If the caller holds no record for the key.
        """
        meta_name = self._names(key, owner)[1]
        async with self._meta_lock:
            metadata = await self._read_meta(meta_name)
            if metadata is None or metadata.expires_at <= datetime.now(timezone.utc):
                raise HandleClaimError()
            if grantee in metadata.grants:
                return metadata
            updated = metadata.model_copy(update={"grants": (*metadata.grants, grantee)})
            await self._write_meta(meta_name, updated)
            return updated

    async def delete(self, key: str, *, owner: HandleOwner) -> bool:
        """Delete the caller's own record for a key.

        Args:
            key: Content-addressed blob key.
            owner: Full owner tuple asserted by the caller.

        Returns:
            Whether the caller had a record.
        """
        bin_name, meta_name = self._names(key, owner)
        async with self._meta_lock:
            if not await self._exists(meta_name):
                return False
            await self._fm.delete_file(bin_name)
            await self._fm.delete_file(meta_name)
            return True

    async def sweep(self, now: datetime | None = None) -> int:
        """Delete every record expired at the cutoff and stale orphan binaries.

        A corrupt or concurrently deleted object is logged and skipped, never
        aborting the pass.

        Args:
            now: Optional expiry cutoff, defaulting to current UTC time.

        Returns:
            Number of expired metadata records removed.
        """
        cutoff = now or datetime.now(timezone.utc)
        orphan_cutoff = datetime.now(timezone.utc) - timedelta(seconds=self._orphan_grace_s)
        found = list(await self._fm.find_files(prefix=self._prefix) or ())
        names = {str(getattr(f, "path", "")) for f in found}
        removed = 0
        for file_metadata in found:
            name = str(getattr(file_metadata, "path", ""))
            try:
                if name.endswith(".meta.json"):
                    metadata = await self._read_meta(name)
                    if metadata is None or metadata.expires_at > cutoff:
                        continue
                    await self._fm.delete_file(name.removesuffix(".meta.json") + ".bin")
                    await self._fm.delete_file(name)
                    removed += 1
                elif name.endswith(".bin") and name.removesuffix(".bin") + ".meta.json" not in names:
                    modified = getattr(file_metadata, "modified", None) or getattr(file_metadata, "updated", None)
                    if isinstance(modified, datetime) and modified.tzinfo is not None and modified < orphan_cutoff:
                        await self._fm.delete_file(name)
            except Exception:  # noqa: BLE001 - one bad object must not stall the sweep
                self.logger.warning("FileManagerBlobStore: sweep skipped %s", name, exc_info=True)
        return removed
