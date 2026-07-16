---
type: Wiki Entity
title: FormEventBinding
id: class:parrot_formdesigner.core.events.FormEventBinding
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Declaración por-formulario de un binding evento → handler.
---

# FormEventBinding

Defined in [`parrot_formdesigner.core.events`](../summaries/mod:parrot_formdesigner.core.events.md).

```python
class FormEventBinding(BaseModel)
```

Declaración por-formulario de un binding evento → handler.

Attributes:
    handler_ref: Logical handler name, namespaced as
        ``'<form_id>.<event>'``. At least one dot is required to
        prevent cross-form collisions (per spec §7 naming decision).
    remote: When ``True``, the HTML5 client bridges the event to the
        server via a ``fetch`` call to the remote endpoint.
    required: When ``True`` and the handler is not registered, the
        dispatcher raises ``RuntimeError`` instead of silently no-op-ing.
