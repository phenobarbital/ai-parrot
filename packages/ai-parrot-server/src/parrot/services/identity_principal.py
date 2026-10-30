"""Resolve channel identities to Navigator principals (FEAT-773 M8)."""

from __future__ import annotations

import logging
from typing import Any, Optional

from parrot.auth.principal import Principal


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

    async def resolve(self, channel: str, channel_user_id: str) -> Optional[Principal]:
        """Return the bound principal, or ``None`` when resolution fails."""
        if not channel or not channel_user_id:
            return None

        channel_user_id = str(channel_user_id)
        if channel == "web":
            return Principal(user_id=channel_user_id, channel="web", channel_user_id=channel_user_id)

        # IdentityStore has no lookup by e-mail. Do not reinterpret an a2a
        # e-mail as provider_user_id because that could bind the wrong row.
        if channel == "a2a" and "@" in channel_user_id:
            return None

        try:
            store = self._store()
            nav_user_id = await store.find_user_by_provider_account(channel, channel_user_id)
            if nav_user_id is None or str(nav_user_id) == "":
                return None

            canonical_identity: Optional[str] = None
            try:
                identity = await store.get_by_provider(nav_user_id, channel)
                if identity is not None:
                    if channel == "msteams":
                        canonical_identity = getattr(identity, "provider_user_id", None)
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
