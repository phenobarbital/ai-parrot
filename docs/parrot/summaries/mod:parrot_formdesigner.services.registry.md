---
type: Wiki Summary
title: parrot_formdesigner.services.registry
id: mod:parrot_formdesigner.services.registry
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Form Registry for the forms abstraction layer.
relates_to:
- concept: class:parrot_formdesigner.services.registry.FormAlreadyExistsError
  rel: defines
- concept: class:parrot_formdesigner.services.registry.FormRegistry
  rel: defines
- concept: class:parrot_formdesigner.services.registry.FormStorage
  rel: defines
- concept: mod:parrot_formdesigner.api._utils
  rel: references
- concept: mod:parrot_formdesigner.core.schema
  rel: references
- concept: mod:parrot_formdesigner.core.style
  rel: references
- concept: mod:parrot_formdesigner.extractors.yaml
  rel: references
- concept: mod:parrot_formdesigner.services.validators
  rel: references
---

# `parrot_formdesigner.services.registry`

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

Multi-tenancy support (FEAT-183):
- Internal state is dict[tenant, dict[form_id, FormSchema]] (nested dict).
- Every public method accepts kwarg-only ``tenant: str | None = None``.
- ``tenant=None`` resolves strictly to ``default_tenant`` — never aggregates.
- ``on_unregister`` callbacks receive ``(form_id, tenant)`` — BREAKING change.

## Classes

- **`FormAlreadyExistsError(ValueError)`** — Raised when registering a form whose ``form_id`` is already taken.
- **`FormStorage(ABC)`** — Abstract base class for form persistence backends.
- **`FormRegistry`** — Thread-safe, multi-tenant registry for FormSchema objects.
