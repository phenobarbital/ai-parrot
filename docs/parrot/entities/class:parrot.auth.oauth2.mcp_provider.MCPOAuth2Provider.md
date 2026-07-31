---
type: Wiki Entity
title: MCPOAuth2Provider
id: class:parrot.auth.oauth2.mcp_provider.MCPOAuth2Provider
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: OAuth2 provider for an MCP server connection.
relates_to:
- concept: class:parrot.auth.oauth2.registry.OAuth2Provider
  rel: extends
---

# MCPOAuth2Provider

Defined in [`parrot.auth.oauth2.mcp_provider`](../summaries/mod:parrot.auth.oauth2.mcp_provider.md).

```python
class MCPOAuth2Provider(OAuth2Provider)
```

OAuth2 provider for an MCP server connection.

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

## Methods

- `def manager(self) -> Any` — Return the underlying OAuth manager.
- `def toolkit_factory(self, credential_resolver: 'CredentialResolver') -> Any` — Build a toolkit instance.
