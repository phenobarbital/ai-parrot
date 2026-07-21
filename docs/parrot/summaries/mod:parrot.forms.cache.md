---
type: Wiki Summary
title: parrot.forms.cache
id: mod:parrot.forms.cache
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Form Cache for the forms abstraction layer.
relates_to:
- concept: class:parrot.forms.cache.FormCache
  rel: defines
- concept: mod:parrot.forms.schema
  rel: references
---

# `parrot.forms.cache`

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
