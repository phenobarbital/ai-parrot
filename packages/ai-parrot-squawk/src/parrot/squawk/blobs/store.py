"""Content-addressed byte-object store with owner/grant ACL, TTL and dedup (FEAT-746 M5)."""

from __future__ import annotations

from abc import ABC, abstractmethod
import hashlib
from datetime import datetime, timezone
from typing import AsyncIterator, Iterable

from pydantic import BaseModel, ConfigDict, Field

from parrot.interagent import HandleClaimError, HandleOwner, MediaType


class BlobMeta(BaseModel):
    """Describe an immutable content-addressed blob and its access policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    media_type: MediaType
    byte_size: int = Field(ge=0)
    created_at: datetime
    expires_at: datetime
    owner: HandleOwner
    grants: tuple[str, ...] = ()
    encrypted: bool = False
    data_class: str = "internal"


def _authorize(meta: BlobMeta, owner: HandleOwner, grantee: str | None, *, now: datetime | None = None) -> None:
    """Authorize an owner or explicit grantee against an unexpired blob.

    Args:
        meta: Blob metadata containing its owner, grants, and expiry.
        owner: Full owner tuple asserted by the caller.
        grantee: Agent identity used for explicit grant access.
        now: Optional current time for deterministic checks.

    Raises:
        HandleClaimError: If the blob is expired or the caller is unauthorized.
    """
    current_time = now or datetime.now(timezone.utc)
    if meta.expires_at <= current_time or (meta.owner != owner and (grantee is None or grantee not in meta.grants)):
        raise HandleClaimError()


def owner_slug(owner: HandleOwner) -> str:
    """Return the stable storage namespace for one owner tuple.

    Blob keys are content addresses, so identical bytes from two owners share a
    key. Each owner keeps its own record (TTL, grants, data class, encryption)
    under ``<key>/<owner_slug>`` so no owner can read, extend or replace another's.

    Args:
        owner: Full owner tuple.

    Returns:
        A 32-hex-character digest of the owner tuple.
    """
    return hashlib.sha256(owner.model_dump_json().encode()).hexdigest()[:32]


def select_record(
    records: Iterable[BlobMeta], owner: HandleOwner, grantee: str | None, *, now: datetime | None = None
) -> BlobMeta:
    """Pick the record a caller may read: its own, else one that granted ``grantee``.

    Args:
        records: Every owner record stored for one key.
        owner: Full owner tuple asserted by the caller.
        grantee: Agent identity used for explicit grant access.
        now: Optional current time for deterministic checks.

    Returns:
        The authorized, unexpired record.

    Raises:
        HandleClaimError: If no record authorizes the caller.
    """
    current_time = now or datetime.now(timezone.utc)
    candidates = list(records)
    for meta in candidates:
        if meta.owner == owner and meta.expires_at > current_time:
            return meta
    if grantee is not None:
        for meta in candidates:
            if grantee in meta.grants and meta.expires_at > current_time:
                return meta
    raise HandleClaimError()


class SquawkBlobStore(ABC):
    """Define content-addressed blob storage with shared ACL and TTL semantics."""

    @abstractmethod
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
        """Hash while writing and publish only after digest verification."""

    @abstractmethod
    async def has(self, key: str, *, owner: HandleOwner | None = None) -> bool:
        """Return whether an unexpired record exists (for ``owner`` when given)."""

    @abstractmethod
    async def meta(self, key: str, *, owner: HandleOwner | None = None) -> BlobMeta | None:
        """Return ``owner``'s record for a key, or any unexpired record when ``owner`` is None."""

    @abstractmethod
    async def open_read(
        self,
        key: str,
        *,
        owner: HandleOwner,
        grantee: str | None = None,
        offset: int = 0,
        length: int | None = None,
    ) -> AsyncIterator[bytes]:
        """Authorize access and yield chunks of the requested plaintext range."""
        if False:
            yield b""

    @abstractmethod
    async def grant(self, key: str, *, owner: HandleOwner, grantee: str) -> BlobMeta:
        """Grant an agent access when requested by the blob owner."""

    @abstractmethod
    async def delete(self, key: str, *, owner: HandleOwner) -> bool:
        """Delete the caller's own record for a blob."""

    @abstractmethod
    async def sweep(self, now: datetime | None = None) -> int:
        """Delete expired objects and return the count."""
