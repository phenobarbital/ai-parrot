"""VaultMCPTokenStorage — adapter bridging MCP SDK's TokenStorage protocol to
AI-Parrot's :class:`~parrot.mcp.oauth.VaultTokenStore`.

The MCP SDK expects a ``TokenStorage`` implementation for persisting OAuth2
tokens and client registration information; this adapter delegates all
storage operations to the encrypted Vault infrastructure already used by the
rest of the platform.

Example:
    >>> storage = VaultMCPTokenStorage("user@co.com", "netsuite")
    >>> await storage.set_tokens(token)
    >>> token = await storage.get_tokens()
"""
from __future__ import annotations

import logging
from typing import Optional

from parrot.mcp.oauth import VaultTokenStore

# MCP SDK protocol and models
from mcp.client.auth.oauth2 import TokenStorage  # noqa: F401 — re-exported for typing
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

logger = logging.getLogger(__name__)


class VaultMCPTokenStorage:
    """MCP SDK ``TokenStorage`` adapter backed by AI-Parrot's Vault.

    Bridges the MCP SDK ``TokenStorage`` protocol to
    :class:`~parrot.mcp.oauth.VaultTokenStore` for encrypted token
    persistence.  A separate vault credential name is used for client
    registration information vs. access tokens.

    Degrades gracefully when the Vault is unavailable: operations log a
    warning and return ``None`` / no-op instead of raising exceptions,
    so the in-memory token state remains usable during the current session.

    Args:
        user_id: Caller's user identifier (scopes token storage per user).
        server_name: MCP server slug (e.g. ``"netsuite"``).
        vault_store: Optional :class:`~parrot.mcp.oauth.VaultTokenStore`
            instance.  A default instance is created when ``None``.

    Example:
        >>> storage = VaultMCPTokenStorage("user@co.com", "netsuite")
        >>> await storage.set_tokens(OAuthToken(access_token="..."))
        >>> token = await storage.get_tokens()
    """

    def __init__(
        self,
        user_id: str,
        server_name: str,
        vault_store: Optional[VaultTokenStore] = None,
    ) -> None:
        self._user_id = user_id
        self._server_name = server_name
        self._vault = vault_store or VaultTokenStore()
        self._logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _client_info_server_name(self) -> str:
        """Return the vault key suffix used for client registration data."""
        return f"__client_info_{self._server_name}"

    # ------------------------------------------------------------------
    # MCP SDK TokenStorage protocol implementation
    # ------------------------------------------------------------------

    async def get_tokens(self) -> OAuthToken | None:
        """Retrieve stored OAuth2 tokens from the Vault.

        Returns:
            :class:`mcp.shared.auth.OAuthToken` if tokens are stored,
            ``None`` if absent or vault is unavailable.
        """
        try:
            data = await self._vault.get(self._user_id, self._server_name)
            if not data:
                return None
            # Filter to only valid OAuthToken fields to avoid Pydantic errors
            valid_fields = set(OAuthToken.model_fields.keys())
            filtered = {k: v for k, v in data.items() if k in valid_fields and v is not None}
            return OAuthToken(**filtered)
        except Exception as exc:
            self._logger.warning(
                "VaultMCPTokenStorage.get_tokens: vault unavailable for %s/%s — %s",
                self._user_id,
                self._server_name,
                exc,
            )
            return None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        """Persist OAuth2 tokens to the Vault.

        Args:
            tokens: :class:`mcp.shared.auth.OAuthToken` to store.
        """
        try:
            if hasattr(tokens, "model_dump"):
                data = {k: v for k, v in tokens.model_dump().items() if v is not None}
            else:
                data = {k: v for k, v in dict(tokens).items() if v is not None}
            await self._vault.set(self._user_id, self._server_name, data)
        except Exception as exc:
            self._logger.warning(
                "VaultMCPTokenStorage.set_tokens: vault unavailable for %s/%s — %s",
                self._user_id,
                self._server_name,
                exc,
            )

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        """Retrieve stored OAuth2 client registration data from the Vault.

        Returns:
            :class:`mcp.shared.auth.OAuthClientInformationFull` if stored,
            ``None`` if absent or vault unavailable.
        """
        try:
            data = await self._vault.get(
                self._user_id, self._client_info_server_name()
            )
            if not data:
                return None
            # Filter to valid OAuthClientInformationFull fields
            valid_fields = set(OAuthClientInformationFull.model_fields.keys())
            filtered = {k: v for k, v in data.items() if k in valid_fields and v is not None}
            return OAuthClientInformationFull(**filtered)
        except Exception as exc:
            self._logger.warning(
                "VaultMCPTokenStorage.get_client_info: vault unavailable for %s/%s — %s",
                self._user_id,
                self._server_name,
                exc,
            )
            return None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        """Persist OAuth2 client registration data to the Vault.

        Uses a separate vault credential key from the access tokens so they
        can be updated independently.

        Args:
            client_info: :class:`mcp.shared.auth.OAuthClientInformationFull`
                to store.
        """
        try:
            if hasattr(client_info, "model_dump"):
                data = {
                    k: v for k, v in client_info.model_dump().items() if v is not None
                }
            else:
                data = {k: v for k, v in dict(client_info).items() if v is not None}
            await self._vault.set(
                self._user_id, self._client_info_server_name(), data
            )
        except Exception as exc:
            self._logger.warning(
                "VaultMCPTokenStorage.set_client_info: vault unavailable for %s/%s — %s",
                self._user_id,
                self._server_name,
                exc,
            )
