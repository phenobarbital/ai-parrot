"""Resolve channel identities to Navigator principals (FEAT-773 M8)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from parrot.auth.principal import Principal

# FEAT-775: Teams identity rows may be stored under either provider name; first match wins.
_CHANNEL_IDENTITY_PROVIDERS: Dict[str, Tuple[str, ...]] = {"msteams": ("msteams", "azure")}

# FEAT-777 D4: providers whose provider_user_id is an Entra object id.
_ENTRA_PROVIDERS: tuple[str, ...] = ("msteams",)
_CANONICAL_CHANNELS = frozenset({"cli", "a2a"})
_SLACK_OWNERS_SQL = """
SELECT user_id, enabled FROM auth.user_identities
WHERE auth_provider = 'slack' AND provider_user_id = $1
"""
_EMAIL_OWNERS_SQL = "SELECT DISTINCT user_id FROM auth.users WHERE lower(email) = $1 AND is_active IS TRUE"
_OID_OWNERS_SQL = """
SELECT DISTINCT user_id FROM auth.user_identities
WHERE provider_user_id = $1 AND auth_provider = ANY($2::text[]) AND enabled IS TRUE
"""


class IdentityPrincipalResolver:
    """Resolve web ids directly and other channels through ``auth.user_identities``."""

    def __init__(self, db_pool: Any) -> None:
        """Initialize the resolver with the navigator-auth database pool.

        Args:
            db_pool: Pool used by navigator-auth's ``IdentityStore``.
        """
        self._db_pool = db_pool
        self.logger = logging.getLogger(__name__)

    def _store(self) -> Any:
        """Build an identity store for the configured pool."""
        from navigator_auth.identity.store import IdentityStore

        return IdentityStore(self._db_pool)

    async def _fetch(self, sql: str, *args: Any) -> list[Any]:
        """Run one read on the authdb pool (raw asyncpg connection)."""
        from parrot.services.identity_mapping import _raw_connection

        async with self._db_pool.acquire() as conn:
            return list(await _raw_connection(conn).fetch(sql, *args))

    async def _slack_owner(self, channel_user_id: str) -> Optional[str]:
        """Return an enabled Slack owner only when every row has the same owner."""
        rows = await self._fetch(_SLACK_OWNERS_SQL, channel_user_id)
        owners = {str(row["user_id"]) for row in rows}
        if len(owners) == 1 and any(bool(row["enabled"]) for row in rows):
            return owners.pop()

        self.logger.warning("Could not resolve Slack principal: matched rows=%d", len(rows))
        return None

    async def _canonical_owner(self, channel_user_id: str) -> Optional[str]:
        """Return the unique active e-mail or enabled Entra identity owner."""
        if "@" in channel_user_id:
            rows = await self._fetch(_EMAIL_OWNERS_SQL, channel_user_id.lower())
        else:
            rows = await self._fetch(_OID_OWNERS_SQL, channel_user_id, list(_ENTRA_PROVIDERS))

        owners = {str(row["user_id"]) for row in rows}
        if len(owners) == 1:
            return owners.pop()

        self.logger.warning("Could not resolve cli/a2a principal: matched owners=%d", len(owners))
        return None

    async def resolve(self, channel: str, channel_user_id: str) -> Optional[Principal]:
        """Return the bound principal, or ``None`` when resolution fails."""
        if not channel or not channel_user_id:
            return None

        channel_user_id = str(channel_user_id)
        if channel == "web":
            return Principal(user_id=channel_user_id, channel="web", channel_user_id=channel_user_id)

        try:
            if channel == "slack":
                nav_user_id = await self._slack_owner(channel_user_id)
                if nav_user_id is None:
                    return None
                return Principal(user_id=nav_user_id, channel=channel, channel_user_id=channel_user_id)

            if channel in _CANONICAL_CHANNELS:
                canonical_identity = channel_user_id.lower() if "@" in channel_user_id else channel_user_id
                nav_user_id = await self._canonical_owner(channel_user_id)
                if nav_user_id is None:
                    return None
                return Principal(
                    user_id=nav_user_id,
                    canonical_identity=canonical_identity,
                    channel=channel,
                    channel_user_id=channel_user_id,
                )

            store = self._store()
            nav_user_id = None
            matched_provider = channel
            for provider in _CHANNEL_IDENTITY_PROVIDERS.get(channel, (channel,)):
                candidate = await store.find_user_by_provider_account(provider, channel_user_id)
                if candidate is not None and str(candidate) != "":
                    nav_user_id, matched_provider = candidate, provider
                    break
            if nav_user_id is None or str(nav_user_id) == "":
                return None

            canonical_identity: Optional[str] = None
            try:
                identity = await store.get_by_provider(nav_user_id, matched_provider)
                if identity is not None:
                    if channel == "msteams":
                        canonical_identity = getattr(identity, "provider_user_id", None) or channel_user_id
                    else:
                        email = getattr(identity, "email", None)
                        canonical_identity = email.lower() if email else None
            except Exception:
                self.logger.warning(
                    "Could not read canonical identity for channel %s",
                    channel,
                    exc_info=True,
                )

            return Principal(
                user_id=str(nav_user_id),
                canonical_identity=canonical_identity,
                channel=channel,
                channel_user_id=channel_user_id,
            )
        except Exception:
            self.logger.warning("Could not resolve principal for channel %s", channel, exc_info=True)
            return None
