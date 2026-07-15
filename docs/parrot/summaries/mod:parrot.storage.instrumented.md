---
type: Wiki Summary
title: parrot.storage.instrumented
id: mod:parrot.storage.instrumented
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: InstrumentedBackend — transparent ConversationBackend wrapper.
relates_to:
- concept: class:parrot.storage.instrumented.InstrumentedBackend
  rel: defines
- concept: mod:parrot.storage.backends.base
  rel: references
- concept: mod:parrot.storage.metrics
  rel: references
---

# `parrot.storage.instrumented`

InstrumentedBackend — transparent ConversationBackend wrapper.

Wraps any ``ConversationBackend`` and records per-method latency and errors
via a ``StorageMetrics`` instance. Zero overhead when ``PARROT_STORAGE_METRICS``
is unset (the factory returns the raw backend in that case).

FEAT-116: dynamodb-fallback-redis — Module 8 (observability hooks).

## Classes

- **`InstrumentedBackend(ConversationBackend)`** — Wraps any ConversationBackend and records per-method latency + errors.
