---
type: Wiki Overview
title: 'TASK-1257: Embedding Stage — EmbeddingModel + FAISS + pgvector'
id: doc:sdd-tasks-completed-task-1257-graphindex-embed-stage-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task implements the **embedding stage** of the GraphIndex pipeline.
  After extractors produce `UniversalNode` instances, this stage batch-embeds their
  summaries/titles via `EmbeddingModel`, builds an in-memory FAISS index for fast
  similarity search, and persists embeddings to
relates_to:
- concept: mod:parrot.embeddings
  rel: mentions
- concept: mod:parrot.embeddings.base
  rel: mentions
- concept: mod:parrot.embeddings.registry
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.embed
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.schema
  rel: mentions
---

# TASK-1257: Embedding Stage — EmbeddingModel + FAISS + pgvector

**Feature**: FEAT-187 — GraphIndex — Structured Knowledge Graph Indexing
**Spec**: `sdd/specs/graphindex.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1253
**Assigned-to**: unassigned

---

## Context

This task implements the **embedding stage** of the GraphIndex pipeline. After extractors produce `UniversalNode` instances, this stage batch-embeds their summaries/titles via `EmbeddingModel`, builds an in-memory FAISS index for fast similarity search, and persists embeddings to pgvector for durable storage. It also populates the `embedding_ref` field on each node.

This stage is consumed by the cross-domain resolution stage (future task) and the GraphIndex toolkit for semantic search queries.

Implements: Spec §3 Module 3 (Embedding Stage).

---

## Scope

- Batch embed `UniversalNode` summaries/titles via `EmbeddingModel.encode()`
- Build FAISS in-memory index from embedding vectors
- Write embeddings to pgvector (persistent storage)
- Use `EmbeddingRegistry` singleton for model caching
- Handle embedding failures gracefully: persist node with `embedding_ref=null`, log for retry
- Populate `embedding_ref` on each successfully embedded node
- Provide methods: `embed_nodes()`, `search_similar()`, `get_embedding()`

**NOT in scope**: cross-domain resolution (uses FAISS but is a separate task), graph assembly, extractors, analytics, toolkit

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/embed.py` | CREATE | Batch embedding, FAISS index management, pgvector persistence |
| `packages/ai-parrot/tests/knowledge/graphindex/test_embed.py` | CREATE | Unit tests for embedding stage |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.embeddings.base import EmbeddingModel    # encode(texts) -> np.ndarray
from parrot.embeddings.registry import EmbeddingRegistry  # singleton cache
from parrot.knowledge.graphindex.schema import UniversalNode
import faiss                                          # already in core deps
import numpy as np
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/embeddings/base.py
class EmbeddingModel:
    def encode(self, texts: list[str]) -> np.ndarray:
        """Encode texts into embedding vectors."""
        ...

# packages/ai-parrot/src/parrot/embeddings/registry.py
class EmbeddingRegistry:
    @classmethod
    def get(cls, model_name: str) -> EmbeddingModel:
        """Get or create a cached EmbeddingModel instance."""
        ...
```

### Does NOT Exist
- ~~`AbstractClient.embed()`~~ — use `parrot.embeddings.EmbeddingModel` instead
- ~~`parrot.embeddings.faiss_index`~~ — FAISS index management is new code in this task
- ~~`parrot.knowledge.graphindex.embed`~~ — does not exist yet; this task creates it

---

## Implementation Notes

### Pattern to Follow
```python
import logging
from typing import Optional
import faiss
import numpy as np

from parrot.embeddings.base import EmbeddingModel
from parrot.embeddings.registry import EmbeddingRegistry
from parrot.knowledge.graphindex.schema import UniversalNode

logger = logging.getLogger(__name__)

class GraphIndexEmbedder:
    """Batch-embed UniversalNode summaries and manage vector indices.

    Provides in-memory FAISS index for fast similarity search and
    pgvector persistence for durable storage.

    Args:
        model_name: Name of the embedding model to use via EmbeddingRegistry.
        dimension: Embedding vector dimension. Defaults to 384.
        pgvector_dsn: Optional DSN for pgvector persistence.
    """

    def __init__(
        self,
        model_name: str = "default",
        dimension: int = 384,
        pgvector_dsn: str | None = None,
    ) -> None:
        self.model: EmbeddingModel = EmbeddingRegistry.get(model_name)
        self.dimension = dimension
        self.index: faiss.IndexFlatL2 = faiss.IndexFlatL2(dimension)
        self._node_id_map: list[str] = []  # index position -> node_id
        self.pgvector_dsn = pgvector_dsn

    async def embed_nodes(
        self, nodes: list[UniversalNode], batch_size: int = 64
    ) -> list[UniversalNode]:
        """Batch-embed nodes and populate embedding_ref.

        Args:
            nodes: List of UniversalNode instances to embed.
            batch_size: Number of nodes per embedding batch.

        Returns:
            The same nodes with embedding_ref populated (or None on failure).
        """
        ...

    async def search_similar(
        self, query_text: str, top_k: int = 10
    ) -> list[tuple[str, float]]:
        """Search for similar nodes by text query.

        Returns:
            List of (node_id, distance) tuples sorted by similarity.
        """
        ...

    def get_embedding(self, node_id: str) -> Optional[np.ndarray]:
        """Retrieve the embedding vector for a specific node."""
        ...

    async def _persist_to_pgvector(
        self, node_id: str, embedding: np.ndarray
    ) -> None:
        """Write a single embedding to pgvector. Log on failure."""
        ...

    def _get_embed_text(self, node: UniversalNode) -> str:
        """Get the text to embed: prefer summary, fall back to title."""
        return node.summary or node.title
```

### Key Constraints
- Async-first, type-hinted, Google-style docstrings
- Embedding failures must NOT crash the pipeline — set `embedding_ref=None` and log
- FAISS index is in-memory; pgvector is the durable store
- Batch processing for efficiency (configurable `batch_size`)
- `embedding_ref` format: `"faiss:{index_position}"` or `"pgvector:{node_id}"` (implementation detail)
- `_node_id_map` tracks the mapping from FAISS index positions to `node_id`
- pgvector connection is optional — if `pgvector_dsn` is None, only FAISS is used

---

## Acceptance Criteria

- [ ] Batch embeds `UniversalNode` summaries/titles via `EmbeddingModel.encode()`
- [ ] FAISS in-memory index built from embedding vectors
- [ ] pgvector persistence implemented (optional, based on DSN)
- [ ] `EmbeddingRegistry` used for model caching
- [ ] Embedding failures handled gracefully: `embedding_ref=None`, logged for retry
- [ ] `embedding_ref` populated on successfully embedded nodes
- [ ] `search_similar()` returns ranked results from FAISS index
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/graphindex/test_embed.py -v`
- [ ] Import works: `from parrot.knowledge.graphindex.embed import GraphIndexEmbedder`

---

## Test Specification

```python
import pytest
import numpy as np
from unittest.mock import MagicMock, AsyncMock, patch
from parrot.knowledge.graphindex.embed import GraphIndexEmbedder
from parrot.knowledge.graphindex.schema import UniversalNode, NodeKind


def make_node(node_id: str, title: str, summary: str | None = None) -> UniversalNode:
    return UniversalNode(
        node_id=node_id,
        kind=NodeKind.DOCUMENT,
        title=title,
        source_uri="test.txt",
        summary=summary,
    )


class TestGraphIndexEmbedder:
    @pytest.fixture
    def mock_model(self):
        model = MagicMock()
        model.encode.return_value = np.random.rand(3, 384).astype(np.float32)
        return model

    @pytest.fixture
    def embedder(self, mock_model):
        with patch("parrot.knowledge.graphindex.embed.EmbeddingRegistry") as reg:
            reg.get.return_value = mock_model
            emb = GraphIndexEmbedder(model_name="test", dimension=384)
        return emb

    @pytest.mark.asyncio
    async def test_embed_nodes_populates_embedding_ref(self, embedder, mock_model):
        nodes = [
            make_node("n1", "Title 1", "Summary 1"),
            make_node("n2", "Title 2", "Summary 2"),
            make_node("n3", "Title 3"),
        ]
        result = await embedder.embed_nodes(nodes)
        assert all(n.embedding_ref is not None for n in result)

    @pytest.mark.asyncio
    async def test_embed_nodes_adds_to_faiss(self, embedder, mock_model):
        nodes = [make_node("n1", "Title 1"), make_node("n2", "Title 2")]
        mock_model.encode.return_value = np.random.rand(2, 384).astype(np.float32)
        await embedder.embed_nodes(nodes)
        assert embedder.index.ntotal == 2

    @pytest.mark.asyncio
    async def test_search_similar_returns_results(self, embedder, mock_model):
        nodes = [make_node("n1", "Title 1"), make_node("n2", "Title 2")]
        mock_model.encode.return_value = np.random.rand(2, 384).astype(np.float32)
        await embedder.embed_nodes(nodes)
        mock_model.encode.return_value = np.random.rand(1, 384).astype(np.float32)
        results = await embedder.search_similar("query", top_k=2)
        assert len(results) == 2
        assert all(isinstance(r, tuple) and len(r) == 2 for r in results)

    @pytest.mark.asyncio
    async def test_embed_failure_sets_none(self, embedder, mock_model):
        mock_model.encode.side_effect = RuntimeError("Model error")
        nodes = [make_node("n1", "Title 1")]
        result = await embedder.embed_nodes(nodes)
        assert result[0].embedding_ref is None

    def test_get_embed_text_prefers_summary(self, embedder):
        node = make_node("n1", "Title", "Summary text")
        assert embedder._get_embed_text(node) == "Summary text"

    def test_get_embed_text_falls_back_to_title(self, embedder):
        node = make_node("n1", "Title Only")
        assert embedder._get_embed_text(node) == "Title Only"

    def test_node_id_map_tracks_positions(self, embedder):
        assert embedder._node_id_map == []
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/graphindex.spec.md` for full context
2. **Check dependencies** — TASK-1253 must be completed (provides `UniversalNode`)
3. **Verify the Codebase Contract** — confirm `EmbeddingModel`, `EmbeddingRegistry` signatures
4. **Update status** in `sdd/tasks/index/graphindex.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1257-graphindex-embed-stage.md`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
