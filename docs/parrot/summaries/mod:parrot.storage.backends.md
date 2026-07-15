---
type: Wiki Summary
title: parrot.storage.backends
id: mod:parrot.storage.backends
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Pluggable ConversationBackend factory and re-exports.
relates_to:
- concept: func:parrot.storage.backends.build_conversation_backend
  rel: defines
- concept: func:parrot.storage.backends.build_overflow_store
  rel: defines
- concept: func:parrot.storage.backends.load_metrics_from_path
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.interfaces.file.gcs
  rel: references
- concept: mod:parrot.interfaces.file.local
  rel: references
- concept: mod:parrot.interfaces.file.s3
  rel: references
- concept: mod:parrot.interfaces.file.tmp
  rel: references
- concept: mod:parrot.storage.backends.base
  rel: references
- concept: mod:parrot.storage.backends.dynamodb
  rel: references
- concept: mod:parrot.storage.backends.mongodb
  rel: references
- concept: mod:parrot.storage.backends.postgres
  rel: references
- concept: mod:parrot.storage.backends.sqlite
  rel: references
- concept: mod:parrot.storage.instrumented
  rel: references
- concept: mod:parrot.storage.metrics
  rel: references
- concept: mod:parrot.storage.overflow
  rel: references
---

# `parrot.storage.backends`

Pluggable ConversationBackend factory and re-exports.

Use ``build_conversation_backend()`` to get the backend specified by
``PARROT_STORAGE_BACKEND``. See docs/storage-backends.md for the full
backend selection matrix and environment variable reference.

FEAT-116: dynamodb-fallback-redis — Module 7 (factory + config wiring).

## Functions

- `async def build_conversation_backend(override: Optional[str]=None) -> ConversationBackend` — Instantiate the backend specified by ``PARROT_STORAGE_BACKEND``.
- `def build_overflow_store(override: Optional[str]=None) -> OverflowStore` — Instantiate the overflow store specified by ``PARROT_OVERFLOW_STORE``.
- `def load_metrics_from_path(path: str) -> 'StorageMetrics'` — Import and return a ``StorageMetrics`` instance from a module path.
