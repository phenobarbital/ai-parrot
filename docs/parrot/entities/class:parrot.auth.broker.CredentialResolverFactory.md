---
type: Wiki Entity
title: CredentialResolverFactory
id: class:parrot.auth.broker.CredentialResolverFactory
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Maps ``auth`` kind to a constructed :class:`CredentialResolver` strategy.
---

# CredentialResolverFactory

Defined in [`parrot.auth.broker`](../summaries/mod:parrot.auth.broker.md).

```python
class CredentialResolverFactory
```

Maps ``auth`` kind to a constructed :class:`CredentialResolver` strategy.

Strategies are built lazily from a :class:`ProviderCredentialConfig` and
injected dependencies.  The factory itself performs no I/O.

Supported kinds
---------------
``obo``
    OBO exchange via ``WorkIQOBOCredentialResolver``
    (``O365Client.acquire_token_on_behalf_of`` + ``VaultTokenSync``).
``oauth2``
    Generic OAuth2 3LO via :class:`~parrot.auth.credentials.OAuthCredentialResolver`.
``static_key``
    Static API-key with OOB capture via ``FirefliesCredentialResolver``
    (or any vault-backed static resolver).
``mcp``
    Thin MCP-backed strategy: reads a bearer token from vault and
    applies it per-call.  Integrated with TASK-1676.

Dependency injection
--------------------
The deps dict carries the runtime objects the factory needs to construct
resolvers (e.g. ``o365_interface``, ``vault``, ``oauth_manager``).
These are never passed via the declarative config; they are provided by
the broker builder in :meth:`CredentialBroker.from_config`.

Args:
    deps: Runtime dependency mapping supplied by the caller
          (e.g. ``{"vault": vault_token_sync, "o365": o365_interface}``).

## Methods

- `def build(self, cfg: ProviderCredentialConfig) -> CredentialResolver` — Build a :class:`CredentialResolver` for *cfg*.
