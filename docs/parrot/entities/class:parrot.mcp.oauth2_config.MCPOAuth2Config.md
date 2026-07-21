---
type: Wiki Entity
title: MCPOAuth2Config
id: class:parrot.mcp.oauth2_config.MCPOAuth2Config
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: OAuth2 configuration for a single MCP server connection.
---

# MCPOAuth2Config

Defined in [`parrot.mcp.oauth2_config`](../summaries/mod:parrot.mcp.oauth2_config.md).

```python
class MCPOAuth2Config(BaseModel)
```

OAuth2 configuration for a single MCP server connection.

All fields are optional to support RFC 7591 dynamic client registration:
when ``client_id`` is ``None`` the MCP SDK's ``OAuthContext`` handles
dynamic registration automatically.

Attributes:
    client_id: OAuth2 client ID.  ``None`` signals RFC 7591 dynamic
        registration.
    client_secret: OAuth2 client secret (optional; not used for public
        clients or PKCE-only flows).
    auth_url: Authorization endpoint URL.
    token_url: Token endpoint URL.
    scopes: Requested OAuth2 scopes.
    grant_type: OAuth2 grant type (default: authorization_code).
    redirect_path: Path for the OAuth2 callback route.
    extra_token_params: Additional parameters to include in token requests.

Example:
    >>> cfg = MCPOAuth2Config(
    ...     client_id="my-app",
    ...     auth_url="https://auth.example.com/authorize",
    ...     token_url="https://auth.example.com/token",
    ...     scopes=["read", "write"],
    ... )
