---
type: Wiki Summary
title: parrot.auth.oauth2.mcp_provider
id: mod:parrot.auth.oauth2.mcp_provider
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: MCPOAuth2Provider — OAuth2 provider for MCP server connections.
relates_to:
- concept: class:parrot.auth.oauth2.mcp_provider.MCPOAuth2Provider
  rel: defines
- concept: func:parrot.auth.oauth2.mcp_provider.register_mcp_oauth2_provider
  rel: defines
- concept: mod:parrot.auth.credentials
  rel: references
- concept: mod:parrot.auth.oauth2.registry
  rel: references
- concept: mod:parrot.mcp.oauth2_config
  rel: references
- concept: mod:parrot.mcp.oauth2_storage
  rel: references
---

# `parrot.auth.oauth2.mcp_provider`

MCPOAuth2Provider — OAuth2 provider for MCP server connections.

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

## Classes

- **`MCPOAuth2Provider(OAuth2Provider)`** — OAuth2 provider for an MCP server connection.

## Functions

- `def register_mcp_oauth2_provider(server_name: str, config: MCPOAuth2Config, storage: Optional['VaultMCPTokenStorage']=None) -> MCPOAuth2Provider` — Create an :class:`MCPOAuth2Provider` and register it in the global registry.
