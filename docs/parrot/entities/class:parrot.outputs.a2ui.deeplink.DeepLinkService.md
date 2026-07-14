---
type: Wiki Entity
title: DeepLinkService
id: class:parrot.outputs.a2ui.deeplink.DeepLinkService
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Mints and consumes single-use, TTL-bound deep-link tokens.
---

# DeepLinkService

Defined in [`parrot.outputs.a2ui.deeplink`](../summaries/mod:parrot.outputs.a2ui.deeplink.md).

```python
class DeepLinkService
```

Mints and consumes single-use, TTL-bound deep-link tokens.

Args:
    redis: An async Redis client exposing ``set(key, value, ex=...)``, ``get(key)``,
        and ``delete(key)`` coroutines (injected — mirrors ``oauth2_base``).
    base_url: Base URL for building resume links (e.g. ``https://app.example``).
    default_ttl: Default token lifetime in seconds.
    key_template: Redis key template with a ``{token_id}`` placeholder.

## Methods

- `async def mint(self, *, session_id: str, user_id: str, agent_id: str, channel: str, action_payload: dict[str, Any], ttl: Optional[int]=None) -> DeepLink` — Mint a single-use deep link for a degraded action.
- `async def consume(self, token: str) -> ResumePayload` — Consume a token exactly once, returning its server-side payload.
