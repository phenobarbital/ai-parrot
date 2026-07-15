---
type: Wiki Entity
title: MCPOAuth2GrantType
id: class:parrot.mcp.oauth2_config.MCPOAuth2GrantType
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: OAuth2 grant types supported for MCP server authentication.
---

# MCPOAuth2GrantType

Defined in [`parrot.mcp.oauth2_config`](../summaries/mod:parrot.mcp.oauth2_config.md).

```python
class MCPOAuth2GrantType(str, Enum)
```

OAuth2 grant types supported for MCP server authentication.

Attributes:
    AUTHORIZATION_CODE: Standard browser-based OAuth2 flow with PKCE.
    CLIENT_CREDENTIALS: Machine-to-machine flow without user interaction.
