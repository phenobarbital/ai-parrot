---
type: Wiki Summary
title: parrot.storage.backends.base
id: mod:parrot.storage.backends.base
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Abstract ConversationBackend interface for pluggable storage.
relates_to:
- concept: class:parrot.storage.backends.base.ConversationBackend
  rel: defines
---

# `parrot.storage.backends.base`

Abstract ConversationBackend interface for pluggable storage.

All storage backends — DynamoDB, SQLite, Postgres, MongoDB — implement this
ABC. The shared contract test suite in tests/storage/test_backend_contract.py
validates that all backends exhibit identical observable behavior.

FEAT-116: dynamodb-fallback-redis — Module 1 (ConversationBackend ABC).
See docs/storage-backends.md for the backend selection matrix.

## Classes

- **`ConversationBackend(ABC)`** — Abstract storage backend for conversations, threads, turns, and artifacts.
