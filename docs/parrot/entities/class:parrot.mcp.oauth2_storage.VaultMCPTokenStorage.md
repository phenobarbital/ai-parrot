---
type: Wiki Entity
title: VaultMCPTokenStorage
id: class:parrot.mcp.oauth2_storage.VaultMCPTokenStorage
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: MCP SDK ``TokenStorage`` adapter backed by AI-Parrot's Vault.
---

# VaultMCPTokenStorage

Defined in [`parrot.mcp.oauth2_storage`](../summaries/mod:parrot.mcp.oauth2_storage.md).

```python
class VaultMCPTokenStorage(TokenStorage)
```

MCP SDK ``TokenStorage`` adapter backed by AI-Parrot's Vault.

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

## Methods

- `async def get_tokens(self) -> OAuthToken | None` — Retrieve stored OAuth2 tokens from the Vault.
- `async def set_tokens(self, tokens: OAuthToken) -> None` — Persist OAuth2 tokens to the Vault.
- `async def get_client_info(self) -> OAuthClientInformationFull | None` — Retrieve stored OAuth2 client registration data from the Vault.
- `async def set_client_info(self, client_info: OAuthClientInformationFull) -> None` — Persist OAuth2 client registration data to the Vault.
