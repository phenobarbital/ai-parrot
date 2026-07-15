---
type: Wiki Entity
title: ConfigurationError
id: class:parrot_formdesigner.services.rest_field_resolver.ConfigurationError
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Raised when resolver cannot determine the internal base URL.
---

# ConfigurationError

Defined in [`parrot_formdesigner.services.rest_field_resolver`](../summaries/mod:parrot_formdesigner.services.rest_field_resolver.md).

```python
class ConfigurationError(Exception)
```

Raised when resolver cannot determine the internal base URL.

This exception surfaces on the *first* internal-mode invocation when
no ``internal_base_url`` constructor arg, ``PARROT_INTERNAL_BASE_URL``
env var, or request-host fallback is available.
