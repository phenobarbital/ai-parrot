---
type: Wiki Entity
title: OAuth2ProviderRegistry
id: class:parrot.auth.oauth2.registry.OAuth2ProviderRegistry
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: In-memory singleton registry of :class:`OAuth2Provider` instances.
---

# OAuth2ProviderRegistry

Defined in [`parrot.auth.oauth2.registry`](../summaries/mod:parrot.auth.oauth2.registry.md).

```python
class OAuth2ProviderRegistry
```

In-memory singleton registry of :class:`OAuth2Provider` instances.

Usage::

    registry = OAuth2ProviderRegistry()
    registry.register(JiraOAuth2Provider())
    provider = registry.get("jira")

The singleton is reset between test cases via :meth:`_reset`.

## Methods

- `def register(self, provider: OAuth2Provider) -> None` — Register *provider*. A duplicate ``provider_id`` overwrites the
- `def get(self, provider_id: str) -> Optional[OAuth2Provider]` — Return the provider for *provider_id*, or ``None`` if not registered.
- `def all(self) -> List[OAuth2Provider]` — Return all registered providers in insertion order.
