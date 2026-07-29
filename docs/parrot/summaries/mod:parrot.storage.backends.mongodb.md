---
type: Wiki Summary
title: parrot.storage.backends.mongodb
id: mod:parrot.storage.backends.mongodb
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: MongoDB conversation backend using motor (via asyncdb[mongo]).
relates_to:
- concept: class:parrot.storage.backends.mongodb.ConversationMongoBackend
  rel: defines
- concept: mod:parrot.storage.backends.base
  rel: references
---

# `parrot.storage.backends.mongodb`

MongoDB conversation backend using motor (via asyncdb[mongo]).

Suitable for GCP deployments or teams already running MongoDB / DocumentDB.
Uses native MongoDB TTL indexes on ``expires_at``.

Note: Mongo's TTL reaper runs once per minute. Tests must NOT assert instant
expiry after writing an expired document — the TTL index is for background
cleanup. Use ``delete_thread_cascade`` or ``delete_session_artifacts`` for
deterministic cleanup in tests.

FEAT-116: dynamodb-fallback-redis — Module 6 (MongoDB backend).

## Classes

- **`ConversationMongoBackend(ConversationBackend)`** — Async MongoDB implementation of ConversationBackend.
