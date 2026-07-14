---
type: Wiki Overview
title: 'Migration — FEAT-201: ai-parrot-embeddings'
id: doc:docs-migration-feat-201-ai-parrot-embeddings-md
tags:
- overview
timestamp: '2026-07-14T22:20:21+00:00'
summary: The concrete backends for embeddings, vector stores, and rerankers moved
relates_to:
- concept: mod:parrot.embeddings
  rel: mentions
- concept: mod:parrot.embeddings.google
  rel: mentions
- concept: mod:parrot.embeddings.huggingface
  rel: mentions
- concept: mod:parrot.embeddings.openai
  rel: mentions
- concept: mod:parrot.rerankers
  rel: mentions
- concept: mod:parrot.rerankers.llm
  rel: mentions
- concept: mod:parrot.rerankers.local
  rel: mentions
- concept: mod:parrot.stores
  rel: mentions
- concept: mod:parrot.stores.arango
  rel: mentions
- concept: mod:parrot.stores.bigquery
  rel: mentions
- concept: mod:parrot.stores.faiss_store
  rel: mentions
- concept: mod:parrot.stores.milvus
  rel: mentions
- concept: mod:parrot.stores.models
  rel: mentions
- concept: mod:parrot.stores.pgvector
  rel: mentions
- concept: mod:parrot.stores.postgres
  rel: mentions
- concept: mod:parrot.tools
  rel: mentions
---

# Migration — FEAT-201: ai-parrot-embeddings

**Feature**: FEAT-201
**Status**: merged (target: next release after dev integration)
**Affects**: anyone installing or vendoring AI-Parrot.

## What changed

The concrete backends for embeddings, vector stores, and rerankers moved
from the `ai-parrot` core distribution to a new sibling package
`ai-parrot-embeddings`.

**Import paths are unchanged** — code such as
`from parrot.stores.pgvector import PgVectorStore` continues to work
without modification, but you must now install the satellite alongside
`ai-parrot`.

The move uses **PEP 420 implicit namespace packages**: the satellite ships
no `__init__.py` at the namespace levels, so Python merges both distributions'
directories automatically.

## Install command mapping

| Old | New |
|-----|-----|
| `pip install ai-parrot[embeddings]` | `pip install ai-parrot ai-parrot-embeddings[huggingface,faiss,pgvector,chroma]` |
| `pip install ai-parrot[milvus]` | `pip install ai-parrot ai-parrot-embeddings[milvus]` |
| `pip install ai-parrot[arango]` | `pip install ai-parrot ai-parrot-embeddings[arango]` |
| `pip install ai-parrot[chroma]` | `pip install ai-parrot ai-parrot-embeddings[chroma]` |
| `pip install ai-parrot[all]` | `pip install ai-parrot[all]` (unchanged — meta-extra now reaches satellite) |
| `pip install ai-parrot[all-fast]` | `pip install ai-parrot[all-fast]` (unchanged for the same reason) |

## Code changes required

**None.** All import paths (`from parrot.embeddings.X`, `from parrot.stores.X`,
`from parrot.rerankers.X`) continue to work exactly as before. No refactoring
is needed in user projects.

## What did NOT change

- `parrot.embeddings.EmbeddingRegistry` and the `supported_embeddings` dispatch map.
- `parrot.stores.AbstractStore`, `supported_stores`, and all shared types
  in `parrot.stores.models` (`Document`, `SearchResult`, `DistanceStrategy`, `StoreConfig`).
- `parrot.stores.{kb,parents,utils,empty,cache}` — higher-level abstractions
  stay in core.
- `parrot.rerankers.{AbstractReranker, create_reranker}` and the lazy
  `__getattr__` resolution.
- `parrot.tools.{vectorstoresearch, multistoresearch}` — core RAG primitives
  stay in core.
- `parrot.embeddings.{base, registry, catalog, matryoshka, processor}` — base
  classes and catalog stay in core.
- `faiss-cpu` stays as a core dependency of `ai-parrot` (episodic memory
  still uses it as default backend).

## What moved

### Embedding backends (to `ai-parrot-embeddings`)

| Module | Class | Extra |
|--------|-------|-------|
| `parrot.embeddings.google` | `GoogleEmbeddingModel` | `google` |
| `parrot.embeddings.huggingface` | `SentenceTransformerModel` | `huggingface` |
| `parrot.embeddings.openai` | `OpenAIEmbeddingModel` | `openai` |

### Vector-store backends (to `ai-parrot-embeddings`)

| Module | Class | Extra |
|--------|-------|-------|
| `parrot.stores.postgres` | `PgVectorStore` | `pgvector` |
| `parrot.stores.pgvector` | `PgVectorStore` (shim) | `pgvector` |
| `parrot.stores.milvus` | `MilvusStore` | `milvus` |
| `parrot.stores.arango` | `ArangoDBStore` | `arango` |
| `parrot.stores.bigquery` | `BigQueryStore` | `bigquery` |
| `parrot.stores.faiss_store` | `FAISSStore` | `faiss` (empty; faiss-cpu in core) |

### Reranker backends (to `ai-parrot-embeddings`)

| Module | Class | Extra |
|--------|-------|-------|
| `parrot.rerankers.local` | `LocalCrossEncoderReranker` | `reranker-local` |
| `parrot.rerankers.llm` | `LLMReranker` | `reranker-llm` |

## Design history

- Spec: [`sdd/specs/ai-parrot-embeddings.spec.md`](../../sdd/specs/ai-parrot-embeddings.spec.md)
- Proposal: [`sdd/proposals/ai-parrot-embeddings.proposal.md`](../../sdd/proposals/ai-parrot-embeddings.proposal.md)
- Research audit: [`sdd/state/FEAT-201/`](../../sdd/state/FEAT-201/) (if present)
