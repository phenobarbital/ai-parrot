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
    """Provide a bounded, asyncio-safe handle store for one process.

    Records are keyed by ``(key, owner)``: handle keys are content addresses, so
    two owners producing identical bytes share a key but never a record. One
    owner can never replace, reset or revoke another owner's handle.
    """

    def __init__(self, *, max_entries: int = 4096) -> None:
        self._items: dict[tuple[str, HandleOwner], ArtifactHandle] = {}
        self._max = max_entries
        self._lock = asyncio.Lock()

    async def put(self, handle: ArtifactHandle) -> str:
        """Store a handle for its owner, evicting the oldest entry when at capacity.

        Re-putting the same key for the same owner refreshes that owner's record
        and keeps its existing grants; other owners' records are untouched.

        Args:
            handle: Handle to store.

        Returns:
            The stored handle key.
        """
        slot = (handle.key, handle.owner)
        async with self._lock:
            existing = self._items.get(slot)
            if existing is None and len(self._items) >= self._max:
                del self._items[next(iter(self._items))]
            if existing is not None:
                merged = tuple(dict.fromkeys((*existing.grants, *handle.grants)))
                handle = handle.model_copy(update={"grants": merged})
            self._items[slot] = handle
            return handle.key

    async def claim(self, key: str, *, owner: HandleOwner, grantee: str | None = None) -> ArtifactHandle:
        """Claim an unexpired handle without disclosing failure details.

        The caller's own record wins; otherwise a record of another owner that
        explicitly granted ``grantee`` is returned.

        Args:
            key: Content-addressed handle key.
            owner: Full owner tuple asserted by the caller.
            grantee: Agent identity used for explicit grant access.

        Returns:
            The claimed handle.

        Raises:
            HandleClaimError: If the handle is missing, expired, or unauthorized.
        """
        now = datetime.now(timezone.utc)
        async with self._lock:
            own = self._items.get((key, owner))
            if own is not None and own.expires_at > now:
                return own
            if grantee is not None:
                for (item_key, _), handle in self._items.items():
                    if item_key == key and grantee in handle.grants and handle.expires_at > now:
                        return handle
            raise HandleClaimError()

    async def grant(self, key: str, *, owner: HandleOwner, grantee: str) -> ArtifactHandle:
        """Grant handle access to an agent when requested by its owner.

        Args:
            key: Content-addressed handle key.
            owner: Full owner tuple asserted by the caller.
            grantee: Agent identity to authorize.

        Returns:
            The updated immutable handle.

        Raises:
            HandleClaimError: If the caller holds no record for the key.
        """
        async with self._lock:
            handle = self._items.get((key, owner))
            if handle is None:
                raise HandleClaimError()
            if grantee in handle.grants:
                return handle
            updated = handle.model_copy(update={"grants": (*handle.grants, grantee)})
            self._items[(key, owner)] = updated
            return updated
