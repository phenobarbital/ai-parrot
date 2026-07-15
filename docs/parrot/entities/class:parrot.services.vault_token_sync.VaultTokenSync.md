---
type: Wiki Entity
title: VaultTokenSync
id: class:parrot.services.vault_token_sync.VaultTokenSync
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Persist OAuth tokens in the encrypted user vault.
---

# VaultTokenSync

Defined in [`parrot.services.vault_token_sync`](../summaries/mod:parrot.services.vault_token_sync.md).

```python
class VaultTokenSync
```

Persist OAuth tokens in the encrypted user vault.

Args:
    db_pool: The ``authdb`` asyncpg pool (``app["authdb"]``).
    redis: The shared Redis client (``app["redis"]``).
    session_ttl: Vault session TTL in seconds (defaults to 1h).
    session_scheme: Session-uuid scheme prefix passed to
        :func:`_synth_session_uuid`. Defaults to the legacy Telegram
        scheme (``"telegram-persistent"``) — existing jira/fireflies/
        workiq callers are unaffected. Non-Telegram surfaces (FEAT-266:
        the O365 device-code CLI resolver) pass a different scheme
        (e.g. ``"cli-persistent"``) so their tokens round-trip under a
        non-Telegram-namespaced key.

Notes:
    All failures (vault unavailable, Redis down, DB error) are logged
    and **swallowed** — callers get either ``None`` (reads) or silent
    success (writes / deletes). This is intentional: token
    persistence is supplementary (Redis is the primary store) and
    must never break the auth flow.

## Methods

- `async def store_tokens(self, nav_user_id: str, provider: str, tokens: Dict[str, Any]) -> None` — Store each ``tokens[key]`` at ``{provider}:{key}`` in the vault.
- `async def read_tokens(self, nav_user_id: str, provider: str) -> Optional[Dict[str, Any]]` — Read all ``{provider}:*`` keys from the user's vault.
- `async def delete_tokens(self, nav_user_id: str, provider: str) -> None` — Remove every ``{provider}:*`` key from the user's vault.
