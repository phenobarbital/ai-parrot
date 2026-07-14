---
type: Wiki Entity
title: ProviderCredentialConfig
id: class:parrot.auth.credentials.ProviderCredentialConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Declarative per-provider credential config (AgentDefinition / manifest).
---

# ProviderCredentialConfig

Defined in [`parrot.auth.credentials`](../summaries/mod:parrot.auth.credentials.md).

```python
class ProviderCredentialConfig(BaseModel)
```

Declarative per-provider credential config (AgentDefinition / manifest).

Attributes:
    provider: Provider identifier (e.g. ``"workiq"``, ``"fireflies"``).
    auth: Auth kind — selects the resolver strategy in
        :class:`~parrot.auth.broker.CredentialResolverFactory`.
    options: Extra options forwarded to the strategy constructor
        (e.g. ``scope``, ``vault_key``, ``capture_url``).
