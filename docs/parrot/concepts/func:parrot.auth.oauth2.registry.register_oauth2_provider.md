---
type: Concept
title: register_oauth2_provider()
id: func:parrot.auth.oauth2.registry.register_oauth2_provider
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module-level convenience for application startup.
---

# register_oauth2_provider

```python
def register_oauth2_provider(provider: OAuth2Provider) -> None
```

Module-level convenience for application startup.

Equivalent to::

    OAuth2ProviderRegistry().register(provider)

Args:
    provider: The provider to register with the global registry.
