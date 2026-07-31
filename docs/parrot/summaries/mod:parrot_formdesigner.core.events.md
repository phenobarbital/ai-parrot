---
type: Wiki Summary
title: parrot_formdesigner.core.events
id: mod:parrot_formdesigner.core.events
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Form lifecycle event models for parrot-formdesigner.
relates_to:
- concept: class:parrot_formdesigner.core.events.EventResolution
  rel: defines
- concept: class:parrot_formdesigner.core.events.FormEventAbort
  rel: defines
- concept: class:parrot_formdesigner.core.events.FormEventBinding
  rel: defines
- concept: class:parrot_formdesigner.core.events.FormEventContext
  rel: defines
- concept: class:parrot_formdesigner.core.events.FormEventsConfig
  rel: defines
- concept: class:parrot_formdesigner.core.events.VisitEventContext
  rel: defines
---

# `parrot_formdesigner.core.events`

Form lifecycle event models for parrot-formdesigner.

This module defines the Pydantic models and typed exception used by the
form lifecycle events system (FEAT-188). All later modules (event_registry,
event_dispatcher, schema extension, handlers, renderer) import from here.

FEAT-329 extends the same pattern with the ``visit.*`` namespace: visit /
assignment lifecycle events reuse the FEAT-188 registry and semantics
(context → handler → ``EventResolution`` | ``FormEventAbort``) without a
``FormSchema`` in the path.

Public surface:
    - FormEventName
    - FormEventBinding
    - FormEventsConfig
    - FormEventContext
    - EventResolution
    - FormEventAbort
    - VisitEventName
    - VisitEventContext

## Classes

- **`FormEventBinding(BaseModel)`** — Declaración por-formulario de un binding evento → handler.
- **`FormEventsConfig(BaseModel)`** — Mapa declarado por-formulario de event → binding.
- **`FormEventContext(BaseModel)`** — Payload passed to a form lifecycle event handler.
- **`VisitEventContext(BaseModel)`** — Payload passed to a visit lifecycle event handler (FEAT-329).
- **`EventResolution(BaseModel)`** — Return value of a form lifecycle event handler.
- **`FormEventAbort(Exception)`** — Cancels a ``before*`` lifecycle event with a typed user-facing response.
