---
type: Concept
title: get_provider()
id: func:parrot.integrations.core.auth.oauth2_providers.get_provider
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Look up an OAuth2 provider by name.
---

# get_provider

```python
def get_provider(name: str) -> OAuth2ProviderConfig
```

Look up an OAuth2 provider by name.

Args:
    name: Provider identifier (case-insensitive).

Returns:
    The matching OAuth2ProviderConfig.

Raises:
    ValueError: If the provider name is not registered.
