---
type: Wiki Entity
title: OAuthAuthorizationServer
id: class:parrot.mcp.oauth_server.OAuthAuthorizationServer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: In-memory OAuth 2.0 authorization server for MCP transports.
---

# OAuthAuthorizationServer

Defined in [`parrot.mcp.oauth_server`](../summaries/mod:parrot.mcp.oauth_server.md).

```python
class OAuthAuthorizationServer
```

In-memory OAuth 2.0 authorization server for MCP transports.

## Methods

- `def register_routes(self, app: web.Application) -> None`
- `def bearer_token_from_header(self, header: Optional[str]) -> Optional[str]`
- `def is_token_valid(self, token: Optional[str]) -> bool`
