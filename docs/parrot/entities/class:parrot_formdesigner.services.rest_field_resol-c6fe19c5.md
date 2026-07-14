---
type: Wiki Entity
title: AdditionalArg
id: class:parrot_formdesigner.services.rest_field_resolver.AdditionalArg
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Extra argument forwarded alongside the uploaded content.
---

# AdditionalArg

Defined in [`parrot_formdesigner.services.rest_field_resolver`](../summaries/mod:parrot_formdesigner.services.rest_field_resolver.md).

```python
class AdditionalArg(BaseModel)
```

Extra argument forwarded alongside the uploaded content.

Visibility controls who supplies the value at submission time:

- ``"public"``: provided by the end user via the rendered form. The
  ``value`` field, if set, acts as a default. ``required=True``
  enforces a non-empty submission.
- ``"private"``: provided by the form designer; ``value`` MUST be set
  and is injected by the backend before forwarding to the target API.
  Frontend-supplied values for private args are ignored.

Attributes:
    name: Argument name as expected by the target API.
    visibility: ``"public"`` or ``"private"``.
    value: Default (public) or fixed (private) value.
    data_type: How to coerce a user-supplied string value.
    required: Whether a public arg must be supplied by the user.
    label: Optional human-readable label (i18n strings live on the field).
    description: Optional help text.
