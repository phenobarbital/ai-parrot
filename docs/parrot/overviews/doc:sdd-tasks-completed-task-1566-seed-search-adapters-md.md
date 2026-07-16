---
type: Wiki Overview
title: 'TASK-1566: Phase 1 — Seed Search Adapters'
id: doc:sdd-tasks-completed-task-1566-seed-search-adapters-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Phase 1 of the 4-phase retrieval pipeline. Seed search selects initial nodes
relates_to:
- concept: mod:parrot.knowledge.graphindex.embed
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.retriever
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.schema
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.hybrid_search
  rel: mentions
---

# TASK-1566: Phase 1 — Seed Search Adapters

**Feature**: FEAT-217 — Graph-Expanded Retrieval Pipeline
**Spec**: `sdd/specs/FEAT-217-graph-expanded-retrieval.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1565
**Assigned-to**: unassigned

---

## Context

Phase 1 of the 4-phase retrieval pipeline. Seed search selects initial nodes
from either HybridPageIndexSearch (PageIndex path) or GraphIndexEmbedder (FAISS path).
Scores must be normalized to [0, 1] regardless of source.

Implements spec Section 2 (Phase 1: Seed Search) and Section 3 (Module 2).

---

## Scope

- Implement `_seed_search()` private method on `GraphExpandedRetriever`
- When `hybrid_search` is available, call `hybrid_search.search()` and convert results to `ScoredNode` list
- When `embedder` is available, call `embedder.search_similar()` and convert results to `ScoredNode` list
- Normalize scores to [0, 1]:
  - HybridPageIndexSearch results: extract score from result dicts, normalize by max
  - GraphIndexEmbedder results: convert L2 distance to similarity (e.g., `1 / (1 + distance)`)
- Mark returned nodes as `is_seed=True`, `hop_distance=0`
- Resolve node metadata (title, kind, source_uri, summary) from `self.nodes` list

**NOT in scope**: Phase 2 expansion (TASK-1567), combining both sources with fusion (deferred to v2 per spec Q4)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/retriever.py` | MODIFY | Add `_seed_search()` method |
| `packages/ai-parrot/tests/knowledge/graphindex/test_retriever.py` | MODIFY | Add seed search tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact imports and signatures. Do not guess alternatives.

### Verified Imports

```python
# From TASK-1565 (created in prior task)
from parrot.knowledge.graphindex.retriever import (
    GraphExpandedRetriever, ScoredNode, ExpansionConfig, BudgetConfig,
)

# verified: packages/ai-parrot/src/parrot/knowledge/graphindex/embed.py:25
from parrot.knowledge.graphindex.embed import GraphIndexEmbedder

# verified: packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py:52
from parrot.knowledge.pageindex.hybrid_search import HybridPageIndexSearch
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/embed.py:122
class GraphIndexEmbedder:
    async def search_similar(self, query_text: str, top_k: int = 10) -> list[tuple[str, float]]:
        """Returns list of (node_id, distance) sorted by ascending L2 distance.
        IMPORTANT: distance (lower = more similar), NOT similarity score."""

# packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py:288
class HybridPageIndexSearch:
    async def search(
        self, query: str, top_k: int = 10,
        use_bm25: bool = True, use_llm_walk: bool = True,
        use_vec: bool = False, use_embedding_walk: Optional[bool] = None,
        rerank: bool = False,
    ) -> list[dict[str, Any]]:
        """Returns list of dicts. Each dict has at minimum 'node_id' and 'score' keys."""

# packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py:70
class UniversalNode(BaseModel):
    node_id: str          # line 74
    title: str            # line 75
    kind: NodeKind        # line 76 (str enum)
    source_uri: Optional[str] = None  # line 80
    summary: Optional[str] = None     # line 81
```

### Does NOT Exist

- ~~`GraphIndexEmbedder.search()`~~ — method is `search_similar()` with `query_text: str`
- ~~`GraphIndexEmbedder.search_similar(query_embedding: np.ndarray, ...)`~~ — actual param is `query_text: str`
- ~~`HybridPageIndexSearch.search_with_graph()`~~ — no such method
- ~~`ScoredNode.from_hybrid_result()`~~ — no factory method exists; construct directly

---

## Implementation Notes

### Score Normalization

GraphIndexEmbedder returns L2 distances (lower = more similar). Convert to similarity:
```python
similarity = 1.0 / (1.0 + distance)
```

HybridPageIndexSearch returns dicts with a `score` key. Normalize by dividing by max score
in the result set (so top result = 1.0). Handle empty results gracefully.

### Node Metadata Resolution

Build a lookup dict from `self.nodes`:
```python
node_map = {n.node_id: n for n in self.nodes}
```
Use this to populate `title`, `kind`, `source_uri`, `summary` on each `ScoredNode`.
If a node_id from search isn't found in the map, log a warning and skip it.

### Key Constraints
- Method must be `async` (both search backends are async)
- Prefer `hybrid_search` if both are available (v1 uses one or the other)
- Return empty list if search returns no results

---

## Acceptance Criteria

- [ ] `_seed_search()` method implemented on `GraphExpandedRetriever`
- [ ] HybridPageIndexSearch path: calls `search()`, normalizes scores to [0, 1]
- [ ] GraphIndexEmbedder path: calls `search_similar()`, converts distance to similarity in [0, 1]
- [ ] All seed nodes have `is_seed=True`, `hop_distance=0`
- [ ] Node metadata (title, kind) resolved from `self.nodes`
- [ ] Graceful handling: empty results, missing node metadata
- [ ] Tests pass: `pytest packages/ai-parrot/tests/knowledge/graphindex/test_retriever.py -v -k "seed"`
- [ ] No linting errors

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/graphindex/test_retriever.py (append)
import pytest
from unittest.mock import AsyncMock, MagicMock
import rustworkx


class TestSeedSearch:
    @pytest.fixture
    def test_nodes(self):
        """Create test UniversalNode list."""
        from parrot.knowledge.graphindex.schema import UniversalNode, NodeKind
        return [
            UniversalNode(node_id=f"n{i}", title=f"Node {i}", kind=NodeKind.DOCUMENT)
            for i in range(10)
        ]

    @pytest.mark.asyncio
    async def test_seed_search_hybrid(self, test_nodes):
        """Phase 1 via HybridPageIndexSearch returns scored seed nodes."""
        from parrot.knowledge.graphindex.retriever import GraphExpandedRetriever
        hybrid = AsyncMock()
        hybrid.search = AsyncMock(return_value=[
            {"node_id": "n0", "score": 10.0},
            {"node_id": "n1", "score": 5.0},
        ])
        graph = rustworkx.PyDiGraph()
        retriever = GraphExpandedRetriever(graph=graph, nodes=test_nodes, hybrid_search=hybrid)
        seeds = await retriever._seed_search("test query", top_k=10)
        assert len(seeds) == 2
        assert seeds[0].is_seed is True
        assert seeds[0].search_score == 1.0  # normalized top score
        assert 0.0 <= seeds[1].search_score <= 1.0

    @pytest.mark.asyncio
    async def test_seed_search_faiss(self, test_nodes):
        """Phase 1 via GraphIndexEmbedder returns scored seed nodes."""
        from parrot.knowledge.graphindex.retriever import GraphExpandedRetriever
        embedder = AsyncMock()
        embedder.search_similar = AsyncMock(return_value=[
            ("n0", 0.1),   # closest (distance)
            ("n1", 0.5),
        ])
        graph = rustworkx.PyDiGraph()
        retriever = GraphExpandedRetriever(graph=graph, nodes=test_nodes, embedder=embedder)
        seeds = await retriever._seed_search("test query", top_k=10)
        assert len(seeds) == 2
        assert seeds[0].is_seed is True
        assert seeds[0].search_score > seeds[1].search_score  # closer = higher score

    @pytest.mark.asyncio
    async def test_no_embedder_fallback(self, test_nodes):
        """When no embedder provided but hybrid_search exists, uses hybrid."""
        from parrot.knowledge.graphindex.retriever import GraphExpandedRetriever
        hybrid = AsyncMock()
        hybrid.search = AsyncMock(return_value=[{"node_id": "n0", "score": 1.0}])
        graph = rustworkx.PyDiGraph()
        retriever = GraphExpandedRetriever(graph=graph, nodes=test_nodes, hybrid_search=hybrid)
        seeds = await retriever._seed_search("query", top_k=5)
        assert len(seeds) == 1
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-217-graph-expanded-retrieval.spec.md` for full context
2. **Check dependencies** — verify TASK-1565 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `search_similar` and `search` signatures
4. **Update status** in `sdd/tasks/index/FEAT-217-graph-expanded-retrieval.json` → `"in-progress"`
5. **Implement** following the scope and codebase contract above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1566-seed-search-adapters.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: 
