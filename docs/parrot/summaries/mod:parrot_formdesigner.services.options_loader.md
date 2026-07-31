---
type: Wiki Summary
title: parrot_formdesigner.services.options_loader
id: mod:parrot_formdesigner.services.options_loader
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: OptionsLoader service for dynamic field option fetching.
relates_to:
- concept: class:parrot_formdesigner.services.options_loader.OptionsLoader
  rel: defines
- concept: mod:parrot_formdesigner.core.options
  rel: references
- concept: mod:parrot_formdesigner.services.auth_context
  rel: references
---

# `parrot_formdesigner.services.options_loader`

OptionsLoader service for dynamic field option fetching.

Fetches ``FieldOption`` lists from remote ``OptionsSource`` endpoints using
``aiohttp.ClientSession``. Features:

- In-memory TTL cache (keyed by ``(source_ref, auth_ref)``)
- Single-flight per cache key — concurrent calls share one in-flight request
- Failure-safe — returns ``[]`` and logs a warning on any error, never raises

Pattern mirrors ``SubmissionForwarder`` for session lifecycle.

## Classes

- **`OptionsLoader`** — Async service that fetches and caches ``FieldOption`` lists.
