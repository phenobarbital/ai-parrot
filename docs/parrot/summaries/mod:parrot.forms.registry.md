---
type: Wiki Summary
title: parrot.forms.registry
id: mod:parrot.forms.registry
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Form Registry for the forms abstraction layer.
relates_to:
- concept: class:parrot.forms.registry.FormRegistry
  rel: defines
- concept: class:parrot.forms.registry.FormStorage
  rel: defines
- concept: mod:parrot.forms.extractors.yaml
  rel: references
- concept: mod:parrot.forms.schema
  rel: references
- concept: mod:parrot.forms.style
  rel: references
---

# `parrot.forms.registry`

Form Registry for the forms abstraction layer.

Provides FormStorage (abstract persistence backend) and FormRegistry
(in-memory registry with optional persistence and async callbacks).

Migrated from parrot/integrations/dialogs/registry.py with:
- FormSchema instead of FormDefinition
- async-first API (asyncio.Lock instead of threading.Lock)
- FormStorage ABC for pluggable persistence backends
- persist= parameter on register()
- load_from_storage() for startup hydration
- Async register/unregister callbacks

## Classes

- **`FormStorage(ABC)`** — Abstract base class for form persistence backends.
- **`FormRegistry`** — Thread-safe registry for FormSchema objects.
