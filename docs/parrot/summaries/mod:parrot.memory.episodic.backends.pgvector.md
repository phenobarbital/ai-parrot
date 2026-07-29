---
type: Wiki Summary
title: parrot.memory.episodic.backends.pgvector
id: mod:parrot.memory.episodic.backends.pgvector
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: PgVector backend for episodic memory storage.
relates_to:
- concept: class:parrot.memory.episodic.backends.pgvector.PgVectorBackend
  rel: defines
- concept: mod:parrot.memory.episodic.models
  rel: references
---

# `parrot.memory.episodic.backends.pgvector`

PgVector backend for episodic memory storage.

Uses asyncpg directly for maximum control over pgvector queries.
Auto-creates schema, table, and indexes on configure().

## Classes

- **`PgVectorBackend`** — PostgreSQL + pgvector backend for episodic memory.
