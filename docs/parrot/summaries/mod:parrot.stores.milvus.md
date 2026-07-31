---
type: Wiki Summary
title: parrot.stores.milvus
id: mod:parrot.stores.milvus
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'MilvusStore: Vector Store implementation using Milvus.'
relates_to:
- concept: class:parrot.stores.milvus.MilvusStore
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.stores.abstract
  rel: references
- concept: mod:parrot.stores.models
  rel: references
---

# `parrot.stores.milvus`

MilvusStore: Vector Store implementation using Milvus.

Provides vector similarity search with:
- Milvus collection management
- Multiple distance metrics (Cosine, L2, Inner Product)
- Metadata filtering via dynamic fields
- Async context manager support
- Document CRUD operations

## Classes

- **`MilvusStore(AbstractStore)`** — A Milvus vector store implementation using pymilvus MilvusClient.
