"""Platform principal for delegated connections (FEAT-773, spec §2).

A connection belongs to the Navigator user (``auth.users.user_id``), never to a
``(channel, channel_user_id)`` pair. Core defines the resolver seam; the server
registers an implementation over ``auth.user_identities`` at startup.
"""
from __future__ import annotations

import logging
from typing import Optional, Protocol, runtime_checkable

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class Principal(BaseModel):
    """The platform identity a connection belongs to (U1).

    Attributes:
        user_id: Navigator ``auth.users.user_id`` serialized as ``str``.
        canonical_identity: Entra OID or lower-cased e-mail, when known.
        tenant_id: Optional tenant.
        channel: Originating channel (web, telegram, slack, msteams, a2a, cli).
        channel_user_id: Raw id on that channel.
    """

    user_id: str
    canonical_identity: Optional[str] = None
    tenant_id: Optional[str] = None
    channel: str
    channel_user_id: str


@runtime_checkable
class PrincipalResolver(Protocol):
    """Maps ``(channel, channel_user_id)`` to a :class:`Principal`."""

    async def resolve(self, channel: str, channel_user_id: str) -> Optional[Principal]:
        """Return the bound principal, or ``None`` (the caller fails closed)."""
        ...


class WebPrincipalResolver:
    """Default resolver: on ``web`` the id IS the Navigator id; other channels resolve to ``None``."""

    async def resolve(self, channel: str, channel_user_id: str) -> Optional[Principal]:
        """Resolve web ids only."""
        if channel == "web" and channel_user_id:
            return Principal(
                user_id=channel_user_id,
                channel="web",
                channel_user_id=channel_user_id,
            )
        return None


_RESOLVER: Optional[PrincipalResolver] = None


def set_principal_resolver(resolver: Optional[PrincipalResolver]) -> None:
    """Register the process-wide resolver (server calls this at startup; ``None`` restores the default)."""
    global _RESOLVER  # pylint: disable=global-statement
    _RESOLVER = resolver


def get_principal_resolver() -> PrincipalResolver:
    """Return the registered resolver, or :class:`WebPrincipalResolver`."""
    return _RESOLVER if _RESOLVER is not None else WebPrincipalResolver()


async def resolve_principal(channel: str, channel_user_id: str) -> Optional[Principal]:
    """Resolve through the registered resolver; ``None`` means "no principal" — never fall back to channel keys."""
    if not channel or not channel_user_id:
        return None

    principal = await get_principal_resolver().resolve(channel, channel_user_id)
    if principal is None:
        logger.debug("No principal resolved for channel %s", channel)
    return principal
