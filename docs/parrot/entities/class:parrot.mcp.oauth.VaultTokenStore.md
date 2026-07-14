---
type: Wiki Entity
title: VaultTokenStore
id: class:parrot.mcp.oauth.VaultTokenStore
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Vault-backed token store that encrypts OAuth tokens using AES-GCM.
relates_to:
- concept: class:parrot.mcp.oauth.TokenStore
  rel: extends
---

# VaultTokenStore

Defined in [`parrot.mcp.oauth`](../summaries/mod:parrot.mcp.oauth.md).

```python
class VaultTokenStore(TokenStore)
```

Vault-backed token store that encrypts OAuth tokens using AES-GCM.

Persists tokens in the DocumentDB Vault (via vault_utils) so they survive
agent restarts. Falls back gracefully when the credential is not found or
vault keys are unavailable.

The credential name follows the pattern ``mcp_oauth_{server_name}_{user_id}``.

Example:
    >>> store = VaultTokenStore()
    >>> await store.set("user@co.com", "netsuite", token_dict)
    >>> token = await store.get("user@co.com", "netsuite")

## Methods

- `async def get(self, user_id: str, server_name: str) -> Optional[Dict[str, Any]]` — Retrieve a stored OAuth token from the Vault.
- `async def set(self, user_id: str, server_name: str, token: Dict[str, Any]) -> None` — Encrypt and persist an OAuth token in the Vault.
- `async def delete(self, user_id: str, server_name: str) -> None` — Remove a stored OAuth token from the Vault.
