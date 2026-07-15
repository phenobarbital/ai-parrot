---
type: Wiki Entity
title: ExternalOAuthValidator
id: class:parrot.mcp.oauth_server.ExternalOAuthValidator
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Validates tokens against external OAuth2 servers using RFC 7662 introspection.
---

# ExternalOAuthValidator

Defined in [`parrot.mcp.oauth_server`](../summaries/mod:parrot.mcp.oauth_server.md).

```python
class ExternalOAuthValidator
```

Validates tokens against external OAuth2 servers using RFC 7662 introspection.

Use this for integrating with external identity providers like Azure AD,
Keycloak, Okta, etc.

## Methods

- `async def validate_token(self, token: str) -> Optional[Dict[str, Any]]` — Validate a token via introspection.
- `async def get_token_info(self, token: str) -> Dict[str, Any]` — Get token info from introspection endpoint (RFC 7662).
- `def clear_cache(self) -> None` — Clear the token cache.
