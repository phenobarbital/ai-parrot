# Feature Specification: Adaptive Agentic RAG

**Feature ID**: FEAT-004
**Date**: 2025-02-18
**Author**: Jesus
**Status**: draft
**Target version**: 0.9.0

---

## 1. Motivation & Business Requirements

### Problem Statement
The current RAG implementation in AI-Parrot uses a static retrieval strategy:
always query PgVector with a fixed similarity threshold. This is suboptimal for:
- Queries that need graph traversal (relational data → ArangoDB better)
- Queries where semantic similarity is insufficient (exact keyword match needed)
- High-cost scenarios where a cheap BM25 lookup suffices before hitting embeddings

### Goals
- Implement an adaptive retrieval strategy that routes queries to the optimal store
- Support multiple backends: PgVector (dense), ArangoDB (graph), BM25 (sparse)
- Minimize LLM calls and embedding costs via smart routing
- Expose a unified `RAGPipeline` interface regardless of backend

### Non-Goals
- Replacing the existing PgVector implementation (must remain compatible)
- Training custom embedding models
- Implementing a new vector store from scratch

---

## 2. Architectural Design

### Overview
A `RAGRouter` analyzes the incoming query and context to select the optimal
retrieval strategy, then delegates to the appropriate `BaseRetriever` implementation.

### Component Diagram
```
Query
  │
  ▼
RAGRouter (selects strategy)
  ├──→ DenseRetriever   (PgVector embeddings)
  ├──→ SparseRetriever  (BM25 keyword)
  └──→ GraphRetriever   (ArangoDB traversal)
         │
         ▼
    RetrievedChunks
         │
         ▼
    RAGPipeline (re-rank + inject into LLM context)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractClient` | uses | RAGPipeline injects context before LLM call |
| `PgVectorStore` | wraps | DenseRetriever delegates to existing store |
| `ArangoDBStore` | wraps | GraphRetriever is new |
| `AbstractBot` | uses | Bots use RAGPipeline via knowledge_base |

### New Public Interfaces
```python
class BaseRetriever(ABC):
    async def retrieve(self, query: str, top_k: int = 5) -> list[RetrievedChunk]

class RAGRouter:
    async def route(self, query: str) -> BaseRetriever

class RAGPipeline:
    async def query(self, query: str) -> RAGResult
```

---

## 3. Module Breakdown

### Module 1: Base Retriever Interface
- **Path**: `parrot/rag/base_retriever.py`
- **Responsibility**: Abstract base class and `RetrievedChunk` data model
- **Depends on**: nothing (new module)

### Module 2: Dense Retriever (PgVector)
- **Path**: `parrot/rag/retrievers/dense.py`
- **Responsibility**: Wraps existing PgVectorStore into BaseRetriever interface
- **Depends on**: Module 1, existing `PgVectorStore`

### Module 3: Sparse Retriever (BM25)
- **Path**: `parrot/rag/retrievers/sparse.py`
- **Responsibility**: BM25 keyword-based retrieval using `rank_bm25`
- **Depends on**: Module 1

### Module 4: Graph Retriever (ArangoDB)
- **Path**: `parrot/rag/retrievers/graph.py`
- **Responsibility**: ArangoDB graph traversal retrieval
- **Depends on**: Module 1, existing ArangoDB client

### Module 5: RAG Router
- **Path**: `parrot/rag/router.py`
- **Responsibility**: Classifies query type and selects optimal retriever
- **Depends on**: Modules 1–4

### Module 6: RAG Pipeline
- **Path**: `parrot/rag/pipeline.py`
- **Responsibility**: Orchestrates router + retriever + re-ranking + context injection
- **Depends on**: Module 5

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_retrieved_chunk_model` | Module 1 | Pydantic model validates correctly |
| `test_dense_retriever_query` | Module 2 | Returns top-k chunks from PgVector |
| `test_sparse_retriever_bm25` | Module 3 | BM25 scoring returns ranked results |
| `test_graph_retriever_traverse` | Module 4 | Graph traversal returns related nodes |
| `test_router_selects_dense` | Module 5 | Semantic queries route to DenseRetriever |
| `test_router_selects_sparse` | Module 5 | Keyword queries route to SparseRetriever |
| `test_pipeline_end_to_end` | Module 6 | Full query → context injection flow |

### Integration Tests
| Test | Description |
|---|---|
| `test_rag_with_pgvector` | Full pipeline against real PgVector instance |
| `test_rag_with_llm` | Pipeline injects context and LLM responds coherently |

---

## 5. Acceptance Criteria

- [ ] `from parrot.rag import RAGPipeline` works
- [ ] `RAGPipeline.query(text)` returns `RAGResult` with sources
- [ ] Router correctly selects retriever in ≥ 80% of test cases
- [ ] All unit tests pass: `pytest tests/unit/rag/ -v`
- [ ] No breaking changes to existing `AbstractBot` knowledge_base integration
- [ ] Latency overhead of routing < 50ms

---

## 6. Implementation Notes & Constraints

### Patterns to Follow
- All classes inherit from appropriate abstract base in `parrot/base/`
- Use `async/await` throughout — no blocking I/O
- Pydantic for `RetrievedChunk`, `RAGResult`, retriever configs
- Log at DEBUG level for retrieval decisions, INFO for router choices

### Known Risks
- ArangoDB graph traversal can be slow — add configurable timeout
- BM25 requires tokenized corpus to be maintained in sync with PgVector

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `rank-bm25` | `>=0.2.2` | BM25 sparse retrieval |
| `python-arango` | `>=8.0` | ArangoDB client (may already exist) |

---

## 7. Open Questions

- [ ] Should the router use an LLM classifier or heuristic rules? — *Owner: Jesus*
- [ ] Do we expose all three retrievers in the public API or just RAGPipeline? — *Owner: Jesus*
