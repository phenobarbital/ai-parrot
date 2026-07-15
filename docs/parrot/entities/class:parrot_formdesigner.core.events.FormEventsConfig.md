---
type: Wiki Entity
title: FormEventsConfig
id: class:parrot_formdesigner.core.events.FormEventsConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Mapa declarado por-formulario de event → binding.
---

# FormEventsConfig

Defined in [`parrot_formdesigner.core.events`](../summaries/mod:parrot_formdesigner.core.events.md).

```python
class FormEventsConfig(BaseModel)
```

Mapa declarado por-formulario de event → binding.

All fields are optional. Forms without an event binding simply skip
that hook without any overhead (no-op by default in the dispatcher).

Attributes:
    onBeforeOpen: Fired before the form is returned to the client.
        Can mutate ``schema_dump`` or abort with ``FormEventAbort``.
    onSchemaLoaded: Fired after the structural schema is rendered.
        Can apply ``schema_overrides``.
    onBeforeSubmit: Fired before validation. Can normalise/replace
        ``payload`` or abort with ``FormEventAbort``.
    onAfterSubmit: Fired after the submission is stored and forwarded.
        Side-effects only; return value ignored by dispatcher.
    onError: Fired when any unhandled exception escapes ``submit_data``.
        Can transform ``user_message``; original exception is re-raised.
