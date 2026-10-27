"""Content-addressed byte-object store with owner/grant ACL, TTL and dedup (FEAT-746 M5)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import AsyncIterator

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
    async def has(self, key: str) -> bool:
        """Return whether metadata exists for a blob key."""

    @abstractmethod
    async def meta(self, key: str) -> BlobMeta | None:
        """Return metadata for a blob key when present."""

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
        """Delete a blob when requested by its owner."""

    @abstractmethod
    async def sweep(self, now: datetime | None = None) -> int:
        """Delete expired objects and return the count."""
