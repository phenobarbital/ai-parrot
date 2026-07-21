---
type: Wiki Entity
title: InternalRestFieldSpec
id: class:parrot_formdesigner.services.rest_field_resolver.InternalRestFieldSpec
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Spec for mode=''internal'': calls a relative path on the running server.'
---

# InternalRestFieldSpec

Defined in [`parrot_formdesigner.services.rest_field_resolver`](../summaries/mod:parrot_formdesigner.services.rest_field_resolver.md).

```python
class InternalRestFieldSpec(_RestFieldSpecBase)
```

Spec for mode='internal': calls a relative path on the running server.

The ``endpoint`` must start with ``"/"``; the resolver prepends
``internal_base_url`` (see resolution order in ``RestFieldResolver``).

Attributes:
    mode: Literal discriminator — always ``"internal"``.
    endpoint: Relative path starting with ``"/"``
        (e.g. ``"/api/v1/networkninja/photo-analyze"``).
    http_method: HTTP verb to use. Defaults to ``"POST"``.
