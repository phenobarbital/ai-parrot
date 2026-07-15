---
type: Wiki Entity
title: RemoteRestFieldSpec
id: class:parrot_formdesigner.services.rest_field_resolver.RemoteRestFieldSpec
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: 'Spec for mode=''remote'': calls an absolute external URL.'
---

# RemoteRestFieldSpec

Defined in [`parrot_formdesigner.services.rest_field_resolver`](../summaries/mod:parrot_formdesigner.services.rest_field_resolver.md).

```python
class RemoteRestFieldSpec(_RestFieldSpecBase)
```

Spec for mode='remote': calls an absolute external URL.

Attributes:
    mode: Literal discriminator — always ``"remote"``.
    endpoint: Absolute URL (must start with ``http://`` or ``https://``).
    http_method: HTTP verb to use. Defaults to ``"POST"``.
    auth_ref: Optional auth reference passed to ``AuthContext.resolve_for``.
