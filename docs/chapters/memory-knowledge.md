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

- [Knowledge Graph & LLM Wiki chapter](knowledge-graph.md) — PageIndex,
  GraphIndex and the agent-maintained wiki built on top of them.
- [LLM Wiki — an agent-maintained knowledge repository](https://github.com/phenobarbital/ai-parrot/wiki/LLM-Wiki-LLM-Wiki-%E2%80%94-an-agent-maintained-knowledge-repository)
- [Execution Memory](https://github.com/phenobarbital/ai-parrot/wiki/Memory-ExecutionMemory-Integration-Guide)
- [Local Knowledge Base](https://github.com/phenobarbital/ai-parrot/wiki/Knowledge-Local-Kb)
- [Parent-Child Retrieval](https://github.com/phenobarbital/ai-parrot/wiki/Stores-%26-Loaders-Parent-Child-Retrieval-%28Small-to-Big%29)
- [DocumentDB](https://github.com/phenobarbital/ai-parrot/wiki/Stores-%26-Loaders-Async-context-manager-para-cleanup-autom%C3%A1tico), [Storage Backends](https://github.com/phenobarbital/ai-parrot/wiki/Stores-%26-Loaders-Storage-Backends-Guide)

## API reference

- [API Reference → Memory](../api-reference/memory.md)
- [API Reference → Stores](../api-reference/stores.md)
