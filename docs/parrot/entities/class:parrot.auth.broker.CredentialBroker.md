---
type: Wiki Entity
title: CredentialBroker
id: class:parrot.auth.broker.CredentialBroker
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Surface-agnostic per-user credential broker.
---

# CredentialBroker

Defined in [`parrot.auth.broker`](../summaries/mod:parrot.auth.broker.md).

```python
class CredentialBroker
```

Surface-agnostic per-user credential broker.

Owns a ``provider_id → resolver`` registry and resolves per-user
credentials at tool-invocation time.  On a successful resolution it
appends a signed entry to the optional :class:`~parrot.security.audit_ledger.AuditLedger`;
on a miss it returns :class:`~parrot.auth.credentials.NeedsAuth` (never
raises on its own — the caller raises :class:`~parrot.auth.credentials.CredentialRequired`
for surfaces to catch).

Usage
-----
.. code-block:: python

    broker = CredentialBroker.from_config(
        configs=[
            ProviderCredentialConfig(provider="workiq", auth="obo",
                                     options={"scope": "..."}),
        ],
        o365_interface=o365,
        o365_oauth_manager=mgr,
        vault=vault,
        audit_ledger=ledger,
    )
    result = await broker.resolve("workiq", "a2a:copilot", "user@example.com")
    if isinstance(result, NeedsAuth):
        raise CredentialRequired(result.provider, result.auth_url, result.auth_kind)

Args:
    audit_ledger: Optional canonical
        :class:`~parrot.security.audit_ledger.AuditLedger`.  When supplied
        a signed entry is appended on every successful resolution.
    identity_mapper: Optional :class:`~parrot.auth.identity.CanonicalIdentityMapper`
        for cross-surface identity normalization.

## Methods

- `def register(self, provider: str, resolver: CredentialResolver, auth_kind: str='oauth2') -> None` — Register a resolver for *provider*.
- `def from_config(cls, configs: List[ProviderCredentialConfig], strict: bool=True, **deps: Any) -> 'CredentialBroker'` — Build a broker from a list of declarative provider configs.
- `async def resolve(self, provider: str, channel: str, user_id: str, **ctx: Any) -> 'ResolvedCredential | NeedsAuth'` — Resolve the per-user credential for *provider*.
