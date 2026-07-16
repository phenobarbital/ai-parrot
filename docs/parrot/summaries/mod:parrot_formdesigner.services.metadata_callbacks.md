---
type: Wiki Summary
title: parrot_formdesigner.services.metadata_callbacks
id: mod:parrot_formdesigner.services.metadata_callbacks
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pydantic I/O models for submission metadata callbacks.
relates_to:
- concept: class:parrot_formdesigner.services.metadata_callbacks.MetadataCallbackInput
  rel: defines
- concept: class:parrot_formdesigner.services.metadata_callbacks.MetadataCallbackOutput
  rel: defines
- concept: mod:parrot_formdesigner.core.schema
  rel: references
---

# `parrot_formdesigner.services.metadata_callbacks`

Pydantic I/O models for submission metadata callbacks.

A *metadata callback* is an async coroutine registered with
``register_form_callback`` (in :mod:`.callback_registry`) and referenced
from a ``FormMetadataField`` with ``source='callback'``. The submit
handler invokes the callback in the enrichment step (after validation,
before storage) and merges its output into the persisted submission.

These models intentionally live in their own module — separate from
``rest_field_resolver`` — because the input payload is shaped around
form *answers* rather than uploaded file content.

## Classes

- **`MetadataCallbackInput(BaseModel)`** — Payload delivered to a registered metadata-callback coroutine.
- **`MetadataCallbackOutput(BaseModel)`** — Return value from a registered metadata-callback coroutine.
