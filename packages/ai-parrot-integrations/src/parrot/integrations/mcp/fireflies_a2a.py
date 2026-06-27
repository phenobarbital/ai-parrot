"""Fireflies.ai MCP credential adapter for the A2A per-user credential bridge.

OQ#6 resolved (2026-06-27 — FEAT-263 / TASK-1648):
Fireflies.ai accepts **exclusively a static API key** from the user. No OAuth
flow is involved. The API key is captured out-of-band (OOB) by directing the
user to a capture page, then stored per-user in vault under ``fireflies:api_key``
via :class:`~parrot.services.vault_token_sync.VaultTokenSync`.

Architecture:
- :class:`FirefliesCredentialResolver`: per-user static-key resolver backed by
  vault (``VaultTokenSync``). First use (key absent) → returns ``None`` and
  surfaces an OOB capture link. After the user submits their key (via
  :meth:`FirefliesCredentialResolver.store_key`), subsequent calls return the key.
- The resolver integrates with :class:`~parrot.a2a.server.A2AServer` via
  :meth:`~parrot.a2a.server.A2AServer.wire_fireflies_resolver`.

Vault key layout::

    fireflies:api_key   → the user's Fireflies.ai API key

Usage::

    from parrot.integrations.mcp.fireflies_a2a import FirefliesCredentialResolver
    from parrot.services.vault_token_sync import VaultTokenSync

    vault = VaultTokenSync(db_pool=app["authdb"], redis=app["redis"])
    resolver = FirefliesCredentialResolver(
        vault_token_sync=vault,
        oob_capture_url="https://your-app.example.com/auth/fireflies/capture",
    )
    a2a_server.wire_fireflies_resolver(resolver)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from parrot.auth.credentials import CredentialResolver

logger = logging.getLogger(__name__)

#: Vault provider prefix used for all Fireflies credentials.
FIREFLIES_PROVIDER: str = "fireflies"

#: Vault key field for the Fireflies API key.
FIREFLIES_API_KEY_FIELD: str = "api_key"


class FirefliesCredentialResolver(CredentialResolver):
    """Per-user static API key resolver for the Fireflies.ai MCP server.

    Fireflies.ai exposes its data via an MCP server authenticated with a
    per-user static API key (no OAuth).  This resolver stores and retrieves
    the API key from the user vault using :class:`VaultTokenSync`.

    On first use (no key in vault) the resolver returns ``None`` and provides
    an OOB capture URL via :meth:`get_auth_url`.  Once the operator calls
    :meth:`store_key` (e.g. from an API endpoint where the user submits their
    key), subsequent :meth:`resolve` calls return the key.

    Vault layout::

        fireflies:api_key   → str (the user's Fireflies.ai API key)

    Args:
        vault_token_sync: A configured
            :class:`~parrot.services.vault_token_sync.VaultTokenSync` instance.
        oob_capture_url: URL to which the A2A bridge directs the user to
            submit their Fireflies API key when none is stored.

    Example::

        vault = VaultTokenSync(db_pool=app["authdb"], redis=app["redis"])
        resolver = FirefliesCredentialResolver(
            vault_token_sync=vault,
            oob_capture_url="https://app.example.com/auth/fireflies/capture",
        )
        a2a_server.wire_fireflies_resolver(resolver)
    """

    PROVIDER: str = FIREFLIES_PROVIDER
    KEY_FIELD: str = FIREFLIES_API_KEY_FIELD

    def __init__(
        self,
        vault_token_sync: Any,
        oob_capture_url: str,
    ) -> None:
        """Initialise the Fireflies credential resolver.

        Args:
            vault_token_sync: Vault token store used for reading/writing the
                per-user API key.  Must implement ``read_tokens`` and
                ``store_tokens`` (see :class:`VaultTokenSync`).
            oob_capture_url: The URL surfaced to the user when they have not
                yet stored a Fireflies API key.  Typically a page in your web
                app where the user can paste their key from
                ``app.fireflies.ai → API Keys``.
        """
        self._vault = vault_token_sync
        self._oob_capture_url = oob_capture_url

    async def resolve(self, channel: str, user_id: str) -> Optional[str]:
        """Return the per-user Fireflies API key from vault, or ``None``.

        Reads ``fireflies:api_key`` from the vault entry for *user_id*.
        Returns ``None`` if the key is absent (user must complete OOB capture).

        Args:
            channel: A2A channel string (e.g. ``"a2a:copilot"``); not used
                for key lookup but accepted for interface consistency.
            user_id: Canonical per-user identity (email / OID).

        Returns:
            The Fireflies API key as a plain string, or ``None`` if not set.
        """
        tokens: Optional[Dict[str, Any]] = await self._vault.read_tokens(
            user_id, self.PROVIDER
        )
        if tokens and (api_key := tokens.get(self.KEY_FIELD)):
            logger.debug(
                "FirefliesCredentialResolver: API key found for user=%s", user_id
            )
            return str(api_key)

        logger.debug(
            "FirefliesCredentialResolver: no API key stored for user=%s", user_id
        )
        return None

    async def get_auth_url(self, channel: str, user_id: str) -> str:
        """Return the OOB capture URL where the user can submit their API key.

        The URL is the same for all users (no per-user state is embedded).
        The A2A bridge appends ``?a2a_state=<interaction_id>`` when building
        the consent link, so the capture endpoint can correlate the callback.

        Args:
            channel: A2A channel string (not used here).
            user_id: Canonical per-user identity (not used here).

        Returns:
            The OOB capture URL as configured at construction time.
        """
        return self._oob_capture_url

    async def store_key(self, user_id: str, api_key: str) -> None:
        """Persist the Fireflies API key for *user_id* in the vault.

        Called by the OOB capture endpoint after the user submits their key.
        Subsequent :meth:`resolve` calls will return the stored key.

        Secrets MUST NOT be logged.  Only the fact that a key was stored is
        logged at DEBUG level.

        Args:
            user_id: Canonical per-user identity (email / OID).
            api_key: The Fireflies API key provided by the user.  Stored as
                ``fireflies:api_key`` in the vault; never echoed in logs.
        """
        await self._vault.store_tokens(
            user_id,
            self.PROVIDER,
            {self.KEY_FIELD: api_key},
        )
        logger.debug(
            "FirefliesCredentialResolver: API key stored for user=%s", user_id
        )
