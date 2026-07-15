---
type: Wiki Summary
title: parrot_formdesigner.services.partial_saves
id: mod:parrot_formdesigner.services.partial_saves
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Redis-backed ephemeral storage for partial form answers.
relates_to:
- concept: class:parrot_formdesigner.services.partial_saves.PartialSaveStore
  rel: defines
- concept: mod:parrot_formdesigner.core.partial
  rel: references
---

# `parrot_formdesigner.services.partial_saves`

Redis-backed ephemeral storage for partial form answers.

Provides ``PartialSaveStore`` — a service that stores work-in-progress form
answers in Redis under the key namespace ``parrot:partial:{form_id}:{session_id}``.

Design mirrors ``FormCache`` (services/cache.py) with these differences:
- No in-memory cache tier: partial saves are per-session ephemeral data that
  is not worth local caching across requests.
- Key includes ``session_id`` for isolation between concurrent users.
- ``save()`` implements merge-on-write: new answers are merged over cached
  answers (last-write-wins), and the TTL is refreshed on every write.

## Classes

- **`PartialSaveStore`** — Redis-backed ephemeral storage for partial form answers.
