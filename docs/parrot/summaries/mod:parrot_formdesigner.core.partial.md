---
type: Wiki Summary
title: parrot_formdesigner.core.partial
id: mod:parrot_formdesigner.core.partial
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Ephemeral partial form answer cache model.
relates_to:
- concept: class:parrot_formdesigner.core.partial.PartialFormData
  rel: defines
---

# `parrot_formdesigner.core.partial`

Ephemeral partial form answer cache model.

Represents work-in-progress form answers stored in Redis under the key
``parrot:partial:{form_id}:{session_id}``.  This model is the data contract
between the ``PartialSaveStore`` service and the REST handlers.

## Classes

- **`PartialFormData(BaseModel)`** — Ephemeral partial form answer cache entry.
