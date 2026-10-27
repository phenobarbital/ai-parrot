"""Local-disk Squawk blob storage with temp publication and optional Fernet encryption."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncIterator

from cryptography.fernet import Fernet

from parrot.interagent import HandleClaimError, HandleOwner, MediaType, SquawkError, SquawkErrorCode
from parrot.squawk.blobs.store import BlobMeta, SquawkBlobStore, _authorize

CHUNK = 1024 * 1024
_KEY_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _sweep_expired(root: Path, now: datetime) -> int:
    """Remove expired object pairs synchronously inside a worker thread.

    Args:
        root: Store root containing digest-prefix directories.
        now: Expiry cutoff.

    Returns:
        Number of expired metadata records removed.
    """
    removed = 0
    for meta_path in root.glob("[0-9a-f][0-9a-f]/*.meta.json"):
        meta = BlobMeta.model_validate_json(meta_path.read_text())
        if meta.expires_at > now:
            continue
        hex_digest = meta_path.name.removesuffix(".meta.json")
        meta_path.with_name(f"{hex_digest}.bin").unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)
        removed += 1
    return removed


class LocalDiskBlobStore(SquawkBlobStore):
    """Store content-addressed Squawk blobs on a local filesystem."""

    def __init__(
        self,
        root: Path,
        *,
        encrypt_classes: frozenset[str] = frozenset({"hr", "pii"}),
        key_env: str = "SQUAWK_BLOB_KEY",
    ) -> None:
        """Initialize local storage and optional encryption.

        Args:
            root: Directory that owns blob data and metadata.
            encrypt_classes: Data classes encrypted before publication.
            key_env: Environment variable containing the Fernet key.

        Raises:
            SquawkError: If encryption is configured without a key.
        """
        self._root = Path(root)
        self._tmp = self._root / ".tmp"
        self._encrypt = encrypt_classes
        key = os.environ.get(key_env)
        if encrypt_classes and not key:
            raise SquawkError(SquawkErrorCode.UPSTREAM_FAILED, "no_blob_key")
        self._fernet = Fernet(key.encode()) if key else None
        self._tmp.mkdir(parents=True, exist_ok=True)

    def _paths(self, key: str) -> tuple[Path, Path]:
        """Return binary and metadata paths for a content key.

        Args:
            key: SHA-256-prefixed blob key.

        Returns:
            Binary and metadata paths.

        Raises:
            HandleClaimError: If the key is not a well-formed ``sha256:<64 hex>`` key
                (never used as a path segment otherwise, so no path traversal).
        """
        if not _KEY_RE.fullmatch(key):
            raise HandleClaimError()
        hex_digest = key.split(":", 1)[1]
        directory = self._root / hex_digest[:2]
        return directory / f"{hex_digest}.bin", directory / f"{hex_digest}.meta.json"

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
        """Hash plaintext frames into a temporary object and publish atomically.

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
            SquawkError: If the computed digest differs from the expected digest.
        """
        digest = hashlib.sha256()
        tmp_path = self._tmp / f"{os.getpid()}-{id(frames)}.part"
        byte_size = 0
        published = False
        file_handle = await asyncio.to_thread(tmp_path.open, "wb")
        try:
            try:
                async for chunk in frames:
                    digest.update(chunk)
                    await asyncio.to_thread(file_handle.write, chunk)
                    byte_size += len(chunk)
            finally:
                await asyncio.to_thread(file_handle.close)

            key = f"sha256:{digest.hexdigest()}"
            if expected_digest is not None and expected_digest != key:
                raise SquawkError(SquawkErrorCode.UPSTREAM_FAILED, "digest_mismatch")

            bin_path, meta_path = self._paths(key)
            if await asyncio.to_thread(meta_path.exists):
                return BlobMeta.model_validate_json(await asyncio.to_thread(meta_path.read_text))

            encrypted = data_class in self._encrypt
            if encrypted:
                plaintext = await asyncio.to_thread(tmp_path.read_bytes)
                if self._fernet is None:
                    raise SquawkError(SquawkErrorCode.UPSTREAM_FAILED, "no_blob_key")
                ciphertext = await asyncio.to_thread(self._fernet.encrypt, plaintext)
                await asyncio.to_thread(tmp_path.write_bytes, ciphertext)

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
            await asyncio.to_thread(bin_path.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(os.replace, tmp_path, bin_path)
            published = True
            await asyncio.to_thread(meta_path.write_text, metadata.model_dump_json())
            return metadata
        finally:
            if not published:
                await asyncio.to_thread(tmp_path.unlink, missing_ok=True)

    async def has(self, key: str) -> bool:
        """Return whether metadata exists for a blob key.

        Args:
            key: Content-addressed blob key.

        Returns:
            Whether the blob metadata exists.
        """
        return await asyncio.to_thread(self._paths(key)[1].exists)

    async def meta(self, key: str) -> BlobMeta | None:
        """Load metadata for a blob key.

        Args:
            key: Content-addressed blob key.

        Returns:
            Parsed metadata, or ``None`` when absent.
        """
        meta_path = self._paths(key)[1]
        if not await asyncio.to_thread(meta_path.exists):
            return None
        return BlobMeta.model_validate_json(await asyncio.to_thread(meta_path.read_text))

    async def open_read(
        self,
        key: str,
        *,
        owner: HandleOwner,
        grantee: str | None = None,
        offset: int = 0,
        length: int | None = None,
    ) -> AsyncIterator[bytes]:
        """Yield a plaintext byte range after ACL and expiry checks.

        Encrypted objects must be decrypted in full before the range is sliced,
        which costs memory proportional to the whole object.

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

        payload = await asyncio.to_thread(self._paths(key)[0].read_bytes)
        if metadata.encrypted:
            if self._fernet is None:
                raise SquawkError(SquawkErrorCode.UPSTREAM_FAILED, "no_blob_key")
            payload = await asyncio.to_thread(self._fernet.decrypt, payload)
        end = None if length is None else offset + length
        selected = payload[offset:end]
        for position in range(0, len(selected), CHUNK):
            yield selected[position : position + CHUNK]

    async def grant(self, key: str, *, owner: HandleOwner, grantee: str) -> BlobMeta:
        """Grant read access to an agent when requested by the owner.

        Args:
            key: Content-addressed blob key.
            owner: Full owner tuple asserted by the caller.
            grantee: Agent identity to authorize.

        Returns:
            Updated immutable metadata.

        Raises:
            HandleClaimError: If the blob is missing or the caller is not its owner.
        """
        metadata = await self.meta(key)
        if metadata is None or metadata.owner != owner:
            raise HandleClaimError()
        updated = metadata.model_copy(update={"grants": (*metadata.grants, grantee)})
        await asyncio.to_thread(self._paths(key)[1].write_text, updated.model_dump_json())
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
        bin_path, meta_path = self._paths(key)
        await asyncio.to_thread(bin_path.unlink, missing_ok=True)
        await asyncio.to_thread(meta_path.unlink, missing_ok=True)
        return True

    async def sweep(self, now: datetime | None = None) -> int:
        """Delete every object expired at the supplied cutoff.

        Args:
            now: Optional expiry cutoff, defaulting to current UTC time.

        Returns:
            Number of expired object pairs removed.
        """
        cutoff = now or datetime.now(timezone.utc)
        return await asyncio.to_thread(_sweep_expired, self._root, cutoff)
