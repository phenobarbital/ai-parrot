---
type: Wiki Entity
title: FirefliesCredentialResolver
id: class:parrot.integrations.mcp.fireflies_a2a.FirefliesCredentialResolver
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Per-user static API key resolver for the Fireflies.ai MCP server.
relates_to:
- concept: class:parrot.auth.credentials.CredentialResolver
  rel: extends
---

# FirefliesCredentialResolver

Defined in [`parrot.integrations.mcp.fireflies_a2a`](../summaries/mod:parrot.integrations.mcp.fireflies_a2a.md).

```python
class FirefliesCredentialResolver(CredentialResolver)
```

Per-user static API key resolver for the Fireflies.ai MCP server.

Fireflies.ai exposes its data via an MCP server authenticated with a
per-user static API key (no OAuth).  This resolver stores and retrieves
the API key from the user vault using :class:`VaultTokenSync`.

On first use (no key in vault) the resolver returns ``None`` and provides
an OOB capture URL via :meth:`get_auth_url`.  Once the operator calls
:meth:`store_key` (e.g. from an API endpoint where the user submits their
key), subsequent :meth:`resolve` calls return the key.

Vault layout::

    fireflies:api_key   → str (the user's Fireflies.ai API key)

Args:
    vault_token_sync: A configured
        :class:`~parrot.services.vault_token_sync.VaultTokenSync` instance.
    oob_capture_url: URL to which the A2A bridge directs the user to
        submit their Fireflies API key when none is stored.

Example::

    vault = VaultTokenSync(db_pool=app["authdb"], redis=app["redis"])
    resolver = FirefliesCredentialResolver(
        vault_token_sync=vault,
        oob_capture_url="https://app.example.com/auth/fireflies/capture",
    )
    a2a_server.wire_fireflies_resolver(resolver)

## Methods

- `async def resolve(self, channel: str, user_id: str) -> Optional[str]` — Return the per-user Fireflies API key from vault, or ``None``.
- `async def get_auth_url(self, channel: str, user_id: str) -> str` — Return the OOB capture URL where the user can submit their API key.
- `async def store_key(self, user_id: str, api_key: str) -> None` — Persist the Fireflies API key for *user_id* in the vault.
