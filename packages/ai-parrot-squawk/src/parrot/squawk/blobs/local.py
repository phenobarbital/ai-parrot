"""Local-disk Squawk blob storage with temp publication and optional Fernet encryption."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncIterator

from cryptography.fernet import Fernet

from parrot.interagent import HandleClaimError, HandleOwner, MediaType, SquawkError, SquawkErrorCode
from parrot.squawk.blobs.store import BlobMeta, SquawkBlobStore, owner_slug, select_record

CHUNK = 1024 * 1024
_KEY_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_logger = logging.getLogger(__name__)


def _read_meta(meta_path: Path) -> BlobMeta | None:
    """Parse one metadata file, tolerating corruption and concurrent deletion.

    Args:
        meta_path: Metadata file path.

    Returns:
        Parsed metadata, or ``None`` when missing or unparseable.
    """
    try:
        return BlobMeta.model_validate_json(meta_path.read_text())
    except FileNotFoundError:
        return None
    except Exception:  # noqa: BLE001 - one corrupt record must never stall reads or sweeps
        _logger.warning("LocalDiskBlobStore: unreadable metadata %s", meta_path, exc_info=True)
        return None


def _write_meta_atomic(meta_path: Path, tmp_dir: Path, metadata: BlobMeta) -> None:
    """Write metadata through a temp file and ``os.replace`` so readers never see a partial file.

    Args:
        meta_path: Destination metadata path.
        tmp_dir: Same-filesystem temp directory.
        metadata: Record to persist.
    """
    tmp = tmp_dir / f"{uuid.uuid4().hex}.meta.part"
    tmp.write_text(metadata.model_dump_json())
    os.replace(tmp, meta_path)


def _sweep_expired(root: Path, now: datetime, orphan_cutoff: float) -> int:
    """Remove expired records and stale orphan binaries inside a worker thread.

    Args:
        root: Store root containing digest-prefix directories.
        now: Expiry cutoff.
        orphan_cutoff: POSIX mtime before which a ``.bin`` without metadata is removed.

    Returns:
        Number of expired metadata records removed.
    """
    removed = 0
    for meta_path in root.glob("[0-9a-f][0-9a-f]/*/*.meta.json"):
        try:
            meta = _read_meta(meta_path)
            if meta is None or meta.expires_at > now:
                continue
            slug = meta_path.name.removesuffix(".meta.json")
            meta_path.with_name(f"{slug}.bin").unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)
            removed += 1
        except OSError:
            _logger.warning("LocalDiskBlobStore: sweep skipped %s", meta_path, exc_info=True)
    for bin_path in root.glob("[0-9a-f][0-9a-f]/*/*.bin"):
        try:
            meta_path = bin_path.with_name(bin_path.name.removesuffix(".bin") + ".meta.json")
            if not meta_path.exists() and bin_path.stat().st_mtime < orphan_cutoff:
                bin_path.unlink(missing_ok=True)
        except OSError:
            _logger.warning("LocalDiskBlobStore: orphan sweep skipped %s", bin_path, exc_info=True)
    return removed


class LocalDiskBlobStore(SquawkBlobStore):
    """Store content-addressed Squawk blobs on a local filesystem."""

    def __init__(
        self,
        root: Path,
        *,
        encrypt_classes: frozenset[str] = frozenset({"hr", "pii"}),
        key_env: str = "SQUAWK_BLOB_KEY",
        orphan_grace_s: int = 3600,
        max_bytes: int = 1024 * 1024 * 1024,
    ) -> None:
        """Initialize local storage and optional encryption.

        Args:
            root: Directory that owns blob data and metadata.
            encrypt_classes: Data classes encrypted before publication.
            key_env: Environment variable containing the Fernet key.
            max_bytes: Largest plaintext object accepted by ``put_stream`` (default 1 GiB).
            orphan_grace_s: Age after which a ``.bin`` without metadata is swept.

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
        self._orphan_grace_s = orphan_grace_s
        self._max_bytes = max_bytes
        self._meta_lock = asyncio.Lock()
        self.logger = logging.getLogger(__name__)
        self._tmp.mkdir(parents=True, exist_ok=True)

    def _dir(self, key: str) -> Path:
        """Return the directory holding every owner record for a content key.

        Args:
            key: SHA-256-prefixed blob key.

        Returns:
            The per-key directory.

        Raises:
            HandleClaimError: If the key is not a well-formed ``sha256:<64 hex>`` key
                (never used as a path segment otherwise, so no path traversal).
        """
        if not _KEY_RE.fullmatch(key):
            raise HandleClaimError()
        hex_digest = key.split(":", 1)[1]
        return self._root / hex_digest[:2] / hex_digest

    def _paths(self, key: str, owner: HandleOwner) -> tuple[Path, Path]:
        """Return binary and metadata paths for one owner's record of a key.

        Args:
            key: SHA-256-prefixed blob key.
            owner: Owner tuple.

        Returns:
            Binary and metadata paths.
        """
        directory = self._dir(key)
        slug = owner_slug(owner)
        return directory / f"{slug}.bin", directory / f"{slug}.meta.json"

    async def _records(self, key: str) -> list[BlobMeta]:
        """Load every readable owner record stored for a key.

        Args:
            key: SHA-256-prefixed blob key.

        Returns:
            Parsed records (corrupt files are skipped and logged).
        """
        directory = self._dir(key)

        def _load() -> list[BlobMeta]:
            if not directory.is_dir():
                return []
            return [m for m in (_read_meta(p) for p in sorted(directory.glob("*.meta.json"))) if m is not None]

        return await asyncio.to_thread(_load)

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
        """Hash plaintext frames into a temporary object and publish atomically for ``owner``.

        Dedup is per owner: an unexpired record of the same owner with the same
        data class is reused (its expiry extended to the later of the two); an
        expired one, or one with a different data class, is republished. Other
        owners' records are never returned or modified.

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
            SquawkError: If the computed digest differs from the expected digest.
        """
        digest = hashlib.sha256()
        tmp_path = self._tmp / f"{uuid.uuid4().hex}.part"
        byte_size = 0
        published = False
        file_handle = await asyncio.to_thread(tmp_path.open, "wb")
        try:
            try:
                async for chunk in frames:
                    digest.update(chunk)
                    await asyncio.to_thread(file_handle.write, chunk)
                    byte_size += len(chunk)
                    if byte_size > self._max_bytes:
                        raise SquawkError(SquawkErrorCode.UPSTREAM_FAILED, "blob_too_large")
            finally:
                await asyncio.to_thread(file_handle.close)

            key = f"sha256:{digest.hexdigest()}"
            if expected_digest is not None and expected_digest != key:
                raise SquawkError(SquawkErrorCode.UPSTREAM_FAILED, "digest_mismatch")

            bin_path, meta_path = self._paths(key, owner)
            now = datetime.now(timezone.utc)
            new_expiry = now + timedelta(seconds=ttl_s)
            encrypted = data_class in self._encrypt
            async with self._meta_lock:
                existing = await asyncio.to_thread(_read_meta, meta_path)
                if (
                    existing is not None
                    and existing.expires_at > now
                    and existing.data_class == data_class
                    and existing.encrypted == encrypted
                    and await asyncio.to_thread(bin_path.exists)
                ):
                    if new_expiry > existing.expires_at:
                        existing = existing.model_copy(update={"expires_at": new_expiry})
                        await asyncio.to_thread(_write_meta_atomic, meta_path, self._tmp, existing)
                    return existing

                if encrypted:
                    if self._fernet is None:
                        raise SquawkError(SquawkErrorCode.UPSTREAM_FAILED, "no_blob_key")
                    plaintext = await asyncio.to_thread(tmp_path.read_bytes)
                    ciphertext = await asyncio.to_thread(self._fernet.encrypt, plaintext)
                    await asyncio.to_thread(tmp_path.write_bytes, ciphertext)

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
                await asyncio.to_thread(bin_path.parent.mkdir, parents=True, exist_ok=True)
                await asyncio.to_thread(os.replace, tmp_path, bin_path)
                published = True
                await asyncio.to_thread(_write_meta_atomic, meta_path, self._tmp, metadata)
                return metadata
        finally:
            if not published:
                await asyncio.to_thread(tmp_path.unlink, missing_ok=True)

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
            return await asyncio.to_thread(_read_meta, self._paths(key, owner)[1])
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
        """Yield a plaintext byte range after ACL and expiry checks.

        Plaintext objects are read with ``seek``; encrypted objects must be
        decrypted in full before the range is sliced.

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
        bin_path = self._paths(key, metadata.owner)[0]
        if not await asyncio.to_thread(bin_path.exists):
            raise HandleClaimError()

        if metadata.encrypted:
            if self._fernet is None:
                raise SquawkError(SquawkErrorCode.UPSTREAM_FAILED, "no_blob_key")
            payload = await asyncio.to_thread(self._fernet.decrypt, await asyncio.to_thread(bin_path.read_bytes))
            end = None if length is None else offset + length
            selected = payload[offset:end]
            for position in range(0, len(selected), CHUNK):
                yield selected[position : position + CHUNK]
            return

        remaining = max(metadata.byte_size - offset, 0) if length is None else length
        handle = await asyncio.to_thread(bin_path.open, "rb")
        try:
            await asyncio.to_thread(handle.seek, offset)
            while remaining > 0:
                chunk = await asyncio.to_thread(handle.read, min(CHUNK, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk
        finally:
            await asyncio.to_thread(handle.close)

    async def grant(self, key: str, *, owner: HandleOwner, grantee: str) -> BlobMeta:
        """Grant read access on the caller's own record (idempotent).

        Args:
            key: Content-addressed blob key.
            owner: Full owner tuple asserted by the caller.
            grantee: Agent identity to authorize.

        Returns:
            Updated immutable metadata.

        Raises:
            HandleClaimError: If the caller holds no record for the key.
        """
        meta_path = self._paths(key, owner)[1]
        async with self._meta_lock:
            metadata = await asyncio.to_thread(_read_meta, meta_path)
            if metadata is None or metadata.expires_at <= datetime.now(timezone.utc):
                raise HandleClaimError()
            if grantee in metadata.grants:
                return metadata
            updated = metadata.model_copy(update={"grants": (*metadata.grants, grantee)})
            await asyncio.to_thread(_write_meta_atomic, meta_path, self._tmp, updated)
            return updated

    async def delete(self, key: str, *, owner: HandleOwner) -> bool:
        """Delete the caller's own record for a key.

        Args:
            key: Content-addressed blob key.
            owner: Full owner tuple asserted by the caller.

        Returns:
            Whether the caller had a record.
        """
        bin_path, meta_path = self._paths(key, owner)
        async with self._meta_lock:
            if not await asyncio.to_thread(meta_path.exists):
                return False
            await asyncio.to_thread(bin_path.unlink, missing_ok=True)
            await asyncio.to_thread(meta_path.unlink, missing_ok=True)
            return True

    async def sweep(self, now: datetime | None = None) -> int:
        """Delete every record expired at the cutoff and stale orphan binaries.

        Args:
            now: Optional expiry cutoff, defaulting to current UTC time.

        Returns:
            Number of expired records removed.
        """
        cutoff = now or datetime.now(timezone.utc)
        orphan_cutoff = datetime.now(timezone.utc).timestamp() - self._orphan_grace_s
        return await asyncio.to_thread(_sweep_expired, self._root, cutoff, orphan_cutoff)
