---
type: Wiki Entity
title: BFTokenServiceResolver
id: class:parrot.integrations.msagentsdk.auth.BFTokenServiceResolver
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Resolves per-user tokens from the Bot Framework Token Service.
relates_to:
- concept: class:parrot.auth.credentials.CredentialResolver
  rel: extends
---

# BFTokenServiceResolver

Defined in [`parrot.integrations.msagentsdk.auth`](../summaries/mod:parrot.integrations.msagentsdk.auth.md).

```python
class BFTokenServiceResolver(CredentialResolver)
```

Resolves per-user tokens from the Bot Framework Token Service.

Subclasses :class:`~parrot.auth.credentials.CredentialResolver` and adds
support for the ``turn_context`` keyword argument that is required to
access the SDK token client.

The resolver accepts extra keyword arguments on :meth:`resolve` so it can
coexist with the abstract interface::

    token = await resolver.resolve(
        channel, user_id,
        tool="o365",
        turn_context=turn_context,
    )

Attributes:
    _connections: Maps tool name → Azure Bot OAuth connection name.
    _obo_scopes: Maps tool name → list of OBO target scopes.
    _ledger: Optional audit ledger.
    logger: Logger scoped to this resolver.

## Methods

- `async def resolve(self, channel: str, user_id: str, **kwargs: Any) -> Optional[Any]` — Resolve per-user credentials from the Bot Framework Token Service.
- `async def get_auth_url(self, channel: str, user_id: str) -> str` — Not supported — the BF Token Service uses OAuthCard sign-in.
- `async def is_connected(self, channel: str, user_id: str) -> bool` — Not supported — use resolve() with tool= and turn_context= kwargs.
