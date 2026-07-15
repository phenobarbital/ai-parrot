---
type: Wiki Summary
title: parrot.stores.postgres
id: mod:parrot.stores.postgres
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Module parrot.stores.postgres
relates_to:
- concept: class:parrot.stores.postgres.Base
  rel: defines
- concept: class:parrot.stores.postgres.PgVectorStore
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.stores.abstract
  rel: references
- concept: mod:parrot.stores.models
  rel: references
- concept: mod:parrot.stores.utils.chunking
  rel: references
---

# `parrot.stores.postgres`

## Classes

- **`Base(DeclarativeBase)`**
- **`PgVectorStore(AbstractStore)`** — A PostgreSQL vector store implementation using pgvector, completely independent of Langchain.

## Functions

- `def vector_distance(embedding_column, vector, op)`
