---
type: Wiki Summary
title: parrot.storage.backends.postgres
id: mod:parrot.storage.backends.postgres
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: PostgreSQL conversation backend using asyncpg via asyncdb[pg].
relates_to:
- concept: class:parrot.storage.backends.postgres.ConversationPostgresBackend
  rel: defines
- concept: mod:parrot.storage.backends.base
  rel: references
---

# `parrot.storage.backends.postgres`

PostgreSQL conversation backend using asyncpg via asyncdb[pg].

Production-grade backend for GCP deployments and dev environments with a
shared Postgres instance. Uses JSONB for payload columns.

Requirements:
  - Postgres 12+ (JSONB, GIN indexes assumed).
  - ``PARROT_POSTGRES_DSN`` environment variable.

Limitations:
  - No schema migrations in v1 — auto-create only handles first init.
  - Connection pool config is backend-internal (not surfaced on the ABC).

FEAT-116: dynamodb-fallback-redis — Module 5 (Postgres backend).

## Classes

- **`ConversationPostgresBackend(ConversationBackend)`** — Async PostgreSQL implementation of ConversationBackend.
