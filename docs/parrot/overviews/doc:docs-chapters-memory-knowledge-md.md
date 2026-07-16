---
type: Wiki Overview
title: Memory & Knowledge
id: doc:docs-chapters-memory-knowledge-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'AI-Parrot separates two concerns that often get confused: **memory**'
relates_to:
- concept: mod:parrot.knowledge
  rel: mentions
---

# Memory & Knowledge

AI-Parrot separates two concerns that often get confused: **memory**
(conversation state for a given session) and **knowledge** (long-lived
facts, documents, embeddings used by RAG).

## What lives here

### Memory

- **`ConversationMemory`** — abstract base for per-session histories.
- **`InMemoryConversation`** — process-local store, ideal for tests.
- **`RedisConversation`** — production-grade, multi-process safe,
  TTL-aware.
- **`EpisodicMemoryStore`** — FAISS-backed long-term episodic memory
  for agents that need to remember across sessions.
- **`AnswerMemory`** — cache of (question → answer) pairs for repeat
  queries.

### Knowledge

- **Vector stores** — `AbstractStore` plus concrete back-ends:
  `PgVectorStore`, `FaissStore`, `MilvusStore`, `ArangoStore`,
  `BigQueryStore`. PgVector is the recommended default.
- **`parrot.knowledge`** — context assembly: takes a user query and
  returns ranked, deduplicated, citation-ready chunks.

## Decision matrix

| Use case | Component |
|---|---|
| Track the last N user turns | `RedisConversation` |
| Remember a user across sessions | `EpisodicMemoryStore` |
| Avoid recomputing identical queries | `AnswerMemory` |
| Semantic retrieval over documents | `PgVectorStore` + `knowledge` |

## Read next

- [LLM Wiki — an agent-maintained knowledge repository](../llm-wiki.md)
- [Execution Memory](../EXECUTION_MEMORY.md)
- [Local Knowledge Base](../local_kb.md)
- [Parent-Child Retrieval](../parent-child-retrieval.md)
- [DocumentDB](../documentdb.md), [Storage Backends](../storage-backends.md)

## API reference

- [API Reference → Memory](../api-reference/memory.md)
- [API Reference → Stores](../api-reference/stores.md)
