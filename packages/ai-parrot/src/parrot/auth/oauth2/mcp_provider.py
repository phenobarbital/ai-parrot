"""MCPOAuth2Provider — OAuth2 provider for MCP server connections.

Registers MCP OAuth2 servers in the unified ``OAuth2ProviderRegistry`` so
that :class:`~parrot.auth.oauth2.service.IntegrationsService.list_for_user`
returns them alongside O365, Jira, and other providers.

MCP tools arrive via the MCP protocol itself — the ``toolkit_factory``
returns ``None`` to signal that no separate toolkit is needed.

Example::

    from parrot.auth.oauth2.mcp_provider import register_mcp_oauth2_provider
    from parrot.mcp.oauth2_config import MCPOAuth2Config

    cfg = MCPOAuth2Config(client_id="my-id", scopes=["mcp"])
    register_mcp_oauth2_provider("netsuite", cfg)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar, List, Optional

from parrot.auth.oauth2.registry import (
    OAuth2Provider,
    register_oauth2_provider,
)
from parrot.mcp.oauth2_config import MCPOAuth2Config

if TYPE_CHECKING:  # pragma: no cover
    from parrot.auth.credentials import CredentialResolver
    from parrot.mcp.oauth2_storage import VaultMCPTokenStorage

logger = logging.getLogger(__name__)


class MCPOAuth2Provider(OAuth2Provider):
    """OAuth2 provider for an MCP server connection.

    Each MCP server that uses OAuth2 gets its own provider instance.
    The ``provider_id`` follows the format ``"mcp:{server_name}"``
    (e.g. ``"mcp:netsuite"``), which makes it unique in the registry even
    when multiple MCP servers are configured simultaneously.

    MCP tools are exposed via the MCP protocol — ``toolkit_factory``
    returns ``None`` to signal that no separate toolkit registration is
    required by the integrations service.

    Attributes:
        provider_id: ``"mcp:{server_name}"``.
        display_name: ``"MCP: {server_name}"``.
        default_scopes: Scopes from the ``MCPOAuth2Config``.
        pbac_action_namespace: ``"integration"``.

    Example:
        >>> cfg = MCPOAuth2Config(client_id="my-id", scopes=["mcp"])
        >>> provider = MCPOAuth2Provider("netsuite", cfg, storage=None)
        >>> provider.provider_id
        'mcp:netsuite'
    """

    default_scopes: ClassVar[List[str]] = []

    def __init__(
        self,
        server_name: str,
        config: MCPOAuth2Config,
        storage: Optional["VaultMCPTokenStorage"] = None,
    ) -> None:
        """Initialize the MCP OAuth2 provider.

        Args:
            server_name: MCP server slug (e.g. ``"netsuite"``).
            config: OAuth2 configuration for this server.
            storage: Optional token storage adapter.  ``None`` is acceptable
                when registration is informational only.
        """
        self.provider_id: str = f"mcp:{server_name}"
        self.display_name: str = f"MCP: {server_name}"
        # Instance-level scopes (not ClassVar, intentional)
        self.default_scopes = list(config.scopes)  # type: ignore[assignment]
        self._config = config
        self._storage = storage
        self._logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # OAuth2Provider abstract interface
    # ------------------------------------------------------------------

    @property
    def manager(self) -> Any:
        """Return the underlying OAuth manager.

        MCP OAuth2 flows are driven by the MCP SDK's ``OAuthContext``
        at the transport layer, not by a separate manager object.

        Returns:
            ``None`` — the MCP SDK manages the flow directly.
        """
        return None

    def toolkit_factory(
        self,
        credential_resolver: "CredentialResolver",  # noqa: F821
    ) -> Any:
        """Build a toolkit instance.

        MCP servers expose their tools via the MCP protocol rather than
        through the toolkit registration mechanism.  This method returns
        ``None`` to signal that no toolkit registration is required.

        Args:
            credential_resolver: Resolver for user credentials (unused).

        Returns:
            ``None`` — MCP tools arrive via the MCP protocol.
        """
        return None


# ---------------------------------------------------------------------------
# Factory helper
# ---------------------------------------------------------------------------


def register_mcp_oauth2_provider(
    server_name: str,
    config: MCPOAuth2Config,
    storage: Optional["VaultMCPTokenStorage"] = None,
) -> MCPOAuth2Provider:
    """Create an :class:`MCPOAuth2Provider` and register it in the global registry.

    Convenience wrapper for application startup.  Idempotent: registering
    the same ``server_name`` twice overwrites the previous entry.

    Args:
        server_name: MCP server slug (e.g. ``"netsuite"``).
        config: OAuth2 configuration for this server.
        storage: Optional token storage adapter.

    Returns:
        The newly registered :class:`MCPOAuth2Provider` instance.

    Example:
        >>> cfg = MCPOAuth2Config(client_id="my-id", scopes=["mcp"])
        >>> provider = register_mcp_oauth2_provider("netsuite", cfg)
        >>> OAuth2ProviderRegistry().get("mcp:netsuite") is provider
        True
    """
    provider = MCPOAuth2Provider(server_name, config, storage=storage)
    register_oauth2_provider(provider)
    logger.debug("Registered MCP OAuth2 provider: %s", provider.provider_id)
    return provider
