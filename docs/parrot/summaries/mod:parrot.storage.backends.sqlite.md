---
type: Wiki Summary
title: parrot.storage.backends.sqlite
id: mod:parrot.storage.backends.sqlite
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: SQLite conversation backend — zero-dependency local storage.
relates_to:
- concept: class:parrot.storage.backends.sqlite.ConversationSQLiteBackend
  rel: defines
- concept: mod:parrot.storage.backends.base
  rel: references
---

# `parrot.storage.backends.sqlite`

SQLite conversation backend — zero-dependency local storage.

Uses ``aiosqlite`` (a transitive dependency of ``asyncdb[sqlite]``) for
async SQLite access.  Suitable for:
  - Data-analyst laptops without Docker or AWS credentials.
  - CI environments without external services.

Limitations (see docs/storage-backends.md):
  - Single-writer: SQLite serializes writes. Not suitable for multi-process
    deployments. For multi-worker local setups, use Postgres via Docker.
  - No built-in background TTL sweeper in v1. Expired rows are filtered on
    read paths; call ``sweep_expired()`` explicitly when desired.
  - File path only (no ``:memory:`` URIs) in v1; the factory always provides
    a real path.

FEAT-116: dynamodb-fallback-redis — Module 4 (SQLite backend).

## Classes

- **`ConversationSQLiteBackend(ConversationBackend)`** — Async SQLite implementation of ConversationBackend.
