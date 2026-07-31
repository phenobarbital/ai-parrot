---
type: Wiki Overview
title: 'TASK-1548: Implement embedding beam walk (Phase B, flag-gated)'
id: doc:sdd-tasks-completed-task-1548-embedding-beam-walk-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module 5 of FEAT-237 — the Phase B embedding-guided beam walk. Instead of
  serializing the entire tree to JSON for the LLM walk, this beam search descends
  the tree using local `(n_children, d) @ (d,)` matmuls at each level, keeping top
  `beam_width` branches. The LLM never reads th
relates_to:
- concept: mod:parrot.knowledge.pageindex.embedding_store
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.hybrid_search
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.utils
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.vector_walk
  rel: mentions
---

# TASK-1548: Implement embedding beam walk (Phase B, flag-gated)

**Feature**: FEAT-237 — PageIndex Embedding Router
**Spec**: `sdd/specs/pageindex-embedding-router.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1546, TASK-1547
**Assigned-to**: unassigned

---

## Context

Module 5 of FEAT-237 — the Phase B embedding-guided beam walk. Instead of serializing the entire tree to JSON for the LLM walk, this beam search descends the tree using local `(n_children, d) @ (d,)` matmuls at each level, keeping top `beam_width` branches. The LLM never reads the whole ToC — it only sees the narrow candidate set.

Phase B is flag-gated via `use_embedding_walk` on `HybridPageIndexSearch`. When off, the system behaves identically to Phase A. When on, the beam walk acts as a *proposer* — the LLM walk / reranker remains the arbiter (platform invariant: deterministic matmul proposes, probabilistic LLM decides).

Spec reference: §2 Data Models (vector_walk.py), §3 Module 5, §4 Unit Tests.

---

## Scope

- Create `vector_walk.py` with:
  - `embedding_tree_walk(tree, query_vec, store, beam_width=3, max_depth=10) -> list[str]`
  - `FlatMatrixSearch` helper class for brute-force cosine over child submatrices.
- Wire into `HybridPageIndexSearch`:
  - When `use_embedding_walk=True`, call `embedding_tree_walk()` to get candidate node_ids.
  - Feed candidates to `_rrf_fuse` or use to restrict the subtree fed to `_llm_rank`.
- Write unit tests for beam walk logic + depth limiting.

**NOT in scope**: Deciding the final Phase B integration mode (replace vs pre-filter vs RRF-only — see open question Q1). Default to RRF fusion for now. Toolkit wiring (TASK-1549).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/vector_walk.py` | CREATE | `embedding_tree_walk()` + `FlatMatrixSearch` |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py` | MODIFY | Wire `use_embedding_walk` flag to beam walk call |
| `tests/knowledge/pageindex/test_embedding_beam_walk.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.

### Verified Imports

```python
from parrot.knowledge.pageindex.hybrid_search import HybridPageIndexSearch  # verified
from parrot.knowledge.pageindex.embedding_store import NodeEmbeddingStore  # from TASK-1546
from parrot.knowledge.pageindex.utils import find_node_by_id, get_nodes  # verified: hybrid_search.py:25
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py (after TASK-1547)
class HybridPageIndexSearch:
    def __init__(self, tree, adapter, reranker=None, model=None,
                 default_bm25_k=20, content_loader=None,
                 embedding_store=None,          # added by TASK-1547
                 use_vec_rank=False,             # added by TASK-1547
                 use_embedding_walk=False)       # added by TASK-1547
    def _vec_rank(self, query, top_k) -> list[str]  # added by TASK-1547
    async def search(self, query, top_k=10, use_bm25=True,
                     use_llm_walk=True, use_vec=False, rerank=False)  # updated by TASK-1547

# packages/ai-parrot/src/parrot/knowledge/pageindex/embedding_store.py (from TASK-1546)
class NodeEmbeddingStore:
    def load_tree_matrix(self, tree_name) -> Optional[tuple[np.ndarray, list[str]]]
    def build_tree_matrix(self, tree_name, nodes, embed_fn) -> tuple[np.ndarray, list[str]]

# Tree structure convention:
# Each node: {"node_id": str, "title": str, "summary": str, "nodes": list[dict]}
# tree: {"doc_name": str, "structure": list[dict]}  — structure is list of root nodes
```

### Does NOT Exist

- ~~`parrot.knowledge.pageindex.vector_walk`~~ — does not exist yet; this task creates it
- ~~`embedding_tree_walk()`~~ — function does not exist yet
- ~~`FlatMatrixSearch`~~ — class does not exist yet
- ~~`HybridPageIndexSearch._beam_walk()`~~ — no such method; the beam walk is a standalone function

---

## Implementation Notes

### Pattern to Follow

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/vector_walk.py

import numpy as np
from typing import Optional


class FlatMatrixSearch:
    """Brute-force cosine similarity over a subset of embeddings."""

    def __init__(self, matrix: np.ndarray, node_ids: list[str]):
        # L2-normalize rows for cosine sim via dot product
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        self._matrix = matrix / np.maximum(norms, 1e-10)
        self._node_ids = node_ids

    def search(self, query_vec: np.ndarray, top_k: int) -> list[tuple[str, float]]:
        query_norm = query_vec / max(np.linalg.norm(query_vec), 1e-10)
        scores = self._matrix @ query_norm  # (N,)
        top_idx = np.argsort(scores)[::-1][:top_k]
        return [(self._node_ids[i], float(scores[i])) for i in top_idx]


async def embedding_tree_walk(
    tree: dict,
    query_vec: np.ndarray,
    store: "NodeEmbeddingStore",
    beam_width: int = 3,
    max_depth: int = 10,
) -> list[str]:
    """Beam search over per-node embeddings to propose candidate node_ids.

    At each level, scores children via cosine similarity (matmul),
    keeps top beam_width branches, and descends.
    """
    candidates = []
    # Start from root nodes
    current_nodes = tree.get("structure", tree.get("nodes", []))
    for depth in range(max_depth):
        if not current_nodes:
            break
        # Get embeddings for current-level children
        # Score children, keep top beam_width
        # Descend into kept branches
        # Collect leaf/branch node_ids
        ...
    return candidates
```

### Key Constraints

- The beam walk is `async` because future integration may need `await` for embedding (even though pure matmul is sync).
- `max_depth` limits recursion depth — must be respected even if the tree is deeper.
- `beam_width` controls how many branches survive at each level. Default 3 is a good tradeoff.
- The walk should collect BOTH branch and leaf node_ids — a branch node may itself be a relevant result.
- L2-normalize both query and matrix rows before dot product for true cosine similarity.
- The beam walk acts as a *proposer* — it produces a candidate list that can be fused via RRF or used to restrict the LLM walk's input.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/pageindex/retriever.py` — the LLM walk this will eventually complement
- `packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py` — integration target
- `packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py` — `find_node_by_id`, `get_nodes`

---

## Acceptance Criteria

- [ ] `embedding_tree_walk()` returns a list of node_id strings
- [ ] Beam walk respects `max_depth` — stops descending after max_depth levels
- [ ] Beam walk respects `beam_width` — keeps at most beam_width branches per level
- [ ] `FlatMatrixSearch.search()` returns sorted (node_id, score) tuples
- [ ] `use_embedding_walk=True` in `HybridPageIndexSearch` triggers beam walk integration
- [ ] `use_embedding_walk=False` does not affect search output (AC7 flag-gating)
- [ ] All tests pass: `pytest tests/knowledge/pageindex/test_embedding_beam_walk.py -v`
- [ ] No linting errors

---

## Test Specification

```python
# tests/knowledge/pageindex/test_embedding_beam_walk.py
import pytest
import numpy as np


@pytest.fixture
def deep_tree():
    """A tree with 3 levels for beam walk testing."""
    return {
        "doc_name": "test-doc",
        "structure": [
            {"node_id": "0001", "title": "Root", "summary": "Root summary", "nodes": [
                {"node_id": "0002", "title": "Branch A", "summary": "About A", "nodes": [
                    {"node_id": "0004", "title": "Leaf A1", "summary": "Detail A1", "nodes": []},
                    {"node_id": "0005", "title": "Leaf A2", "summary": "Detail A2", "nodes": []},
                ]},
                {"node_id": "0003", "title": "Branch B", "summary": "About B", "nodes": [
                    {"node_id": "0006", "title": "Leaf B1", "summary": "Detail B1", "nodes": []},
                ]},
            ]},
        ],
    }


class TestEmbeddingTreeWalk:
    @pytest.mark.asyncio
    async def test_returns_candidates(self, deep_tree):
        """Beam walk returns a non-empty list of node_ids."""
        ...

    @pytest.mark.asyncio
    async def test_respects_max_depth(self, deep_tree):
        """Beam walk stops at max_depth."""
        ...

    @pytest.mark.asyncio
    async def test_respects_beam_width(self, deep_tree):
        """Beam walk keeps at most beam_width branches per level."""
        ...


class TestFlatMatrixSearch:
    def test_search_returns_sorted(self):
        """FlatMatrixSearch returns results sorted by descending score."""
        rng = np.random.default_rng(42)
        matrix = rng.standard_normal((5, 256)).astype(np.float32)
        node_ids = [f"node_{i}" for i in range(5)]
        searcher = FlatMatrixSearch(matrix, node_ids)
        query = rng.standard_normal(256).astype(np.float32)
        results = searcher.search(query, top_k=3)
        assert len(results) == 3
        scores = [s for _, s in results]
        assert scores == sorted(scores, reverse=True)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/pageindex-embedding-router.spec.md` for full context
2. **Check dependencies** — verify TASK-1546 and TASK-1547 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — read `hybrid_search.py` (post TASK-1547) to confirm signatures
4. **Update status** in `sdd/tasks/index/pageindex-embedding-router.json` → `"in-progress"`
5. **Implement** following the scope and contract above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1548-embedding-beam-walk.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-06-15
**Notes**: Created vector_walk.py with FlatMatrixSearch and embedding_tree_walk().
Wired use_embedding_walk flag into HybridPageIndexSearch.search() as 4th RRF signal.
Test for "no embeddings" was updated to reflect correct fallback behavior (beam walk
collects current-level nodes when children have no embeddings). All 9 tests pass.

**Deviations from spec**: test_no_embeddings_returns_empty renamed to
test_no_embeddings_fallback with corrected expectation (fallback to current-level
nodes, not empty list).
