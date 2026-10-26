"""Owner-bound artifact handles for transport-free inter-agent exchange."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from parrot.interagent.descriptors import HandleDescriptor, MediaType
from parrot.interagent.provenance import HandleProvenance

HANDLE_UNAVAILABLE = "handle_unavailable"


class HandleClaimError(Exception):
    """Report every failed handle claim without revealing why it failed."""

    def __init__(self) -> None:
        super().__init__(HANDLE_UNAVAILABLE)


def handle_key(data: bytes) -> str:
    """Build a content-addressed SHA-256 handle key.

    Args:
        data: Exact artifact bytes.

    Returns:
        A key prefixed with ``sha256:``.
    """
    return "sha256:" + hashlib.sha256(data).hexdigest()


class HandleOwner(BaseModel):
    """Identify the agent, user, tenant, and session that own a handle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_id: str
    user_id: str
    tenant_id: str
    session_id: str


class ArtifactHandle(BaseModel):
    """Reference artifact bytes through bounded metadata and provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    media_type: MediaType
    byte_size: int = Field(ge=0)
    ttl_s: int = Field(ge=1)
    expires_at: datetime
    owner: HandleOwner
    grants: tuple[str, ...] = ()
    descriptor: HandleDescriptor
    provenance: HandleProvenance
    affordances: tuple[str, ...] = ()


class HandleStore(Protocol):
    """Store owner-bound handles and enforce claim and grant authorization."""

    async def put(self, handle: ArtifactHandle) -> str:
        """Store a handle and return its content key."""
        ...

    async def claim(self, key: str, *, owner: HandleOwner, grantee: str | None = None) -> ArtifactHandle:
        """Return an unexpired handle to its owner or an explicitly granted agent."""
        ...

    async def grant(self, key: str, *, owner: HandleOwner, grantee: str) -> ArtifactHandle:
        """Grant access to an agent when requested by the handle owner."""
        ...


class InMemoryHandleStore:
    """Provide a bounded, asyncio-safe handle store for one process."""

    def __init__(self, *, max_entries: int = 4096) -> None:
        self._items: dict[str, ArtifactHandle] = {}
        self._max = max_entries
        self._lock = asyncio.Lock()

    async def put(self, handle: ArtifactHandle) -> str:
        """Store a handle, evicting the oldest entry when at capacity.

        Args:
            handle: Handle to store.

        Returns:
            The stored handle key.
        """
        async with self._lock:
            if handle.key not in self._items and len(self._items) >= self._max:
                oldest_key = next(iter(self._items))
                del self._items[oldest_key]
            self._items[handle.key] = handle
            return handle.key

    async def claim(self, key: str, *, owner: HandleOwner, grantee: str | None = None) -> ArtifactHandle:
        """Claim an unexpired handle without disclosing failure details.

        Args:
            key: Content-addressed handle key.
            owner: Full owner tuple asserted by the caller.
            grantee: Agent identity used for explicit grant access.

        Returns:
            The claimed handle.

        Raises:
            HandleClaimError: If the handle is missing, expired, or unauthorized.
        """
        async with self._lock:
            handle = self._items.get(key)
            if (
                handle is None
                or handle.expires_at <= datetime.now(timezone.utc)
                or (owner != handle.owner and grantee not in handle.grants)
            ):
                raise HandleClaimError()
            return handle

    async def grant(self, key: str, *, owner: HandleOwner, grantee: str) -> ArtifactHandle:
        """Grant handle access to an agent when requested by its owner.

        Args:
            key: Content-addressed handle key.
            owner: Full owner tuple asserted by the caller.
            grantee: Agent identity to authorize.

        Returns:
            The updated immutable handle.

        Raises:
            HandleClaimError: If the handle is missing or the caller is not its owner.
        """
        async with self._lock:
            handle = self._items.get(key)
            if handle is None or owner != handle.owner:
                raise HandleClaimError()
            updated = handle.model_copy(update={"grants": (*handle.grants, grantee)})
            self._items[key] = updated
            return updated
