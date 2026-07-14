---
type: Wiki Summary
title: parrot_formdesigner.services.cache
id: mod:parrot_formdesigner.services.cache
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Form Cache for the forms abstraction layer.
relates_to:
- concept: class:parrot_formdesigner.services.cache.FormCache
  rel: defines
- concept: mod:parrot_formdesigner.core.schema
  rel: references
---

# `parrot_formdesigner.services.cache`

Form Cache for the forms abstraction layer.

Provides in-memory TTL-based caching for FormSchema objects with optional
Redis backend for distributed caching.

Migrated from parrot/integrations/dialogs/cache.py with:
- FormSchema instead of FormDefinition
- Cleaner async-only API (asyncio.Lock throughout)
- Redis serialization via FormSchema.model_dump_json()
- No watchdog dependency in core (file watching is optional)

## Classes

- **`FormCache`** — In-memory TTL cache for FormSchema with optional Redis backend.
