---
type: Wiki Overview
title: 'TASK-1547: Add _vec_rank dense signal and RRF fusion (Phase A)'
id: doc:sdd-tasks-completed-task-1547-dense-rrf-fusion-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Module 4 of FEAT-237 — the core Phase A change. Adds a dense embedding ranking
  signal (`_vec_rank`) to `HybridPageIndexSearch` and fuses it as a third input to
  `_rrf_fuse`. This closes the synonymy/paraphrase gap: queries that BM25 misses because
  of vocabulary mismatch can now be'
relates_to:
- concept: mod:parrot.embeddings.base
  rel: mentions
- concept: mod:parrot.embeddings.registry
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.embedding_store
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.hybrid_search
  rel: mentions
---

# TASK-1547: Add _vec_rank dense signal and RRF fusion (Phase A)

**Feature**: FEAT-237 — PageIndex Embedding Router
**Spec**: `sdd/specs/pageindex-embedding-router.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1546
**Assigned-to**: unassigned

---

## Context

Module 4 of FEAT-237 — the core Phase A change. Adds a dense embedding ranking signal (`_vec_rank`) to `HybridPageIndexSearch` and fuses it as a third input to `_rrf_fuse`. This closes the synonymy/paraphrase gap: queries that BM25 misses because of vocabulary mismatch can now be captured by cosine similarity over node embeddings.

The dense signal is purely additive — when disabled (`use_vec=False`), search output must be byte-identical to baseline.

Spec reference: §2 Component Diagram, §3 Module 4, §4 Unit Tests, §5 AC1/AC4.

---

## Scope

- Add `embedding_store` (Optional[NodeEmbeddingStore]) param to `HybridPageIndexSearch.__init__`.
- Add `use_vec_rank` and `use_embedding_walk` boolean flags to `__init__`.
- Implement `_vec_rank(self, query: str, top_k: int) -> list[str]`:
  - Embed query via `encode()` on the model from `EmbeddingRegistry`.
  - Matmul against per-tree matrix: `query_vec @ matrix.T`.
  - Return top-k node_ids ranked by cosine similarity.
- Add `use_vec` parameter to `search()`.
- Update `search()` to conditionally call `_vec_rank` and pass three lists to `_rrf_fuse`.
- Wire dirty flag: `mark_dirty()` calls `embedding_store.invalidate_tree()`.
- Lazy matrix rebuild: first `_vec_rank` call after dirty triggers `build_tree_matrix()`.
- Write unit + integration tests.

**NOT in scope**: The beam walk (TASK-1548), toolkit wiring (TASK-1549), or model loading logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py` | MODIFY | Add `_vec_rank`, update `__init__`, `search()`, `mark_dirty()` |
| `tests/knowledge/pageindex/test_dense_rrf_fusion.py` | CREATE | Unit + integration tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.

### Verified Imports

```python
from parrot.knowledge.pageindex.hybrid_search import HybridPageIndexSearch  # verified: __init__.py
from parrot.knowledge.pageindex.embedding_store import NodeEmbeddingStore  # TASK-1546 creates this
from parrot.embeddings.registry import EmbeddingRegistry  # verified: registry.py:51
from parrot.embeddings.base import EmbeddingModel  # verified: base.py
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py
class HybridPageIndexSearch:
    _RRF_K = 60  # module-level constant, line 38
    def __init__(self, tree, adapter, reranker=None, model=None,
                 default_bm25_k=20, content_loader=None)  # line 54
    def mark_dirty(self) -> None  # line 92 — called by set_content_loader, replace_tree
    def replace_tree(self, tree: dict) -> None  # line 96
    def _bm25_rank(self, query: str, top_k: int) -> list[str]  # line 140
    async def _llm_rank(self, query: str) -> list[str]  # line 162
    @staticmethod
    def _rrf_fuse(rankings: list[list[str]], k=60) -> list[tuple[str, float]]  # line 174
    async def search(self, query, top_k=10, use_bm25=True,
                     use_llm_walk=True, rerank=False) -> list[dict]  # line 185

# packages/ai-parrot/src/parrot/knowledge/pageindex/embedding_store.py (from TASK-1546)
class NodeEmbeddingStore:
    def __init__(self, storage_dir, model_id, dimension, cache_size=512)
    def build_tree_matrix(self, tree_name, nodes, embed_fn) -> tuple[np.ndarray, list[str]]
    def load_tree_matrix(self, tree_name) -> Optional[tuple[np.ndarray, list[str]]]
    def invalidate_tree(self, tree_name) -> None

# packages/ai-parrot/src/parrot/embeddings/registry.py
class EmbeddingRegistry:
    async def get_or_create(self, model_name, model_type="huggingface", **kwargs)  # line 218

# packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py
def find_node_by_id(tree, node_id) -> Optional[dict]  # verified: hybrid_search.py:25
def get_nodes(tree) -> list[dict]  # verified: hybrid_search.py:25 — flattens tree to node list
```

### Does NOT Exist

- ~~`HybridPageIndexSearch._vec_rank()`~~ — does not exist yet; this task adds it
- ~~`HybridPageIndexSearch.search(use_vec=...)`~~ — parameter does not exist yet; this task adds it
- ~~`HybridPageIndexSearch.__init__(embedding_store=...)`~~ — parameter does not exist yet

---

## Implementation Notes

### Pattern to Follow

```python
# _vec_rank follows the same pattern as _bm25_rank:
def _vec_rank(self, query: str, top_k: int) -> list[str]:
    if self._embedding_store is None:
        return []
    # Lazy rebuild if dirty
    result = self._embedding_store.load_tree_matrix(self._tree_name)
    if result is None:
        # Need to build — get all nodes, embed
        nodes = get_nodes(self._tree)
        result = self._embedding_store.build_tree_matrix(
            self._tree_name, nodes, self._embed_fn
        )
    matrix, node_order = result
    # Query embedding (sync for now — wrap in to_thread in search())
    query_vec = ...  # from model.encode([query])[0]
    scores = query_vec @ matrix.T  # (d,) @ (d, N) -> (N,)
    top_indices = np.argsort(scores)[::-1][:top_k]
    return [node_order[i] for i in top_indices]

# In search(), add use_vec parameter:
async def search(self, query, top_k=10, use_bm25=True,
                 use_llm_walk=True, use_vec=False, rerank=False):
    rankings = []
    if use_bm25:
        rankings.append(self._bm25_rank(query, top_k))
    if use_llm_walk:
        rankings.append(await self._llm_rank(query))
    if use_vec and self._embedding_store:
        rankings.append(self._vec_rank(query, top_k))
    fused = self._rrf_fuse(rankings)
    ...
```

### Key Constraints

- **Byte-identical baseline**: When `use_vec=False`, the output MUST match the pre-existing behavior exactly. The `_rrf_fuse` call receives only the same two lists as before.
- **Dirty flag**: `mark_dirty()` must call `self._embedding_store.invalidate_tree(tree_name)` if the store exists.
- **Score normalization**: Use numpy matmul (`query_vec @ matrix.T`) — same approach as `HybridBM25Strategy._cosine_sim`. L2-normalize query and matrix rows if not already normalized.
- **`_rrf_fuse` already handles variable-length lists** — its signature is `rankings: list[list[str]]`.
- **`get_nodes(tree)`** flattens the tree into a list of node dicts — use this for `build_tree_matrix` input.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py` — primary edit target
- `packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py` — `get_nodes` for tree flattening
- `packages/ai-parrot/src/parrot/embeddings/registry.py` — model loading via `get_or_create`

---

## Acceptance Criteria

- [ ] `_vec_rank()` returns ranked node_id list via cosine similarity
- [ ] `search(use_vec=False)` output is byte-identical to baseline (AC1)
- [ ] `search(use_vec=True)` produces fused BM25 + LLM + dense results
- [ ] `_rrf_fuse` correctly handles 2-list and 3-list inputs
- [ ] `mark_dirty()` triggers embedding matrix invalidation
- [ ] Dirty flag triggers lazy matrix rebuild on next `_vec_rank` call (AC4)
- [ ] All tests pass: `pytest tests/knowledge/pageindex/test_dense_rrf_fusion.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py`

---

## Test Specification

```python
# tests/knowledge/pageindex/test_dense_rrf_fusion.py
import pytest
import numpy as np
from unittest.mock import MagicMock, AsyncMock, patch


@pytest.fixture
def small_tree():
    return {
        "doc_name": "test-doc",
        "structure": [
            {"node_id": "0001", "title": "Root", "summary": "Root summary", "nodes": [
                {"node_id": "0002", "title": "Section A", "summary": "About topic A", "nodes": []},
                {"node_id": "0003", "title": "Section B", "summary": "About topic B", "nodes": []},
            ]},
        ],
    }


class TestVecRank:
    def test_returns_node_ids(self, small_tree):
        """_vec_rank returns a list of node_id strings."""
        # Setup with mock embedding store
        ...

    def test_disabled_returns_empty(self, small_tree):
        """_vec_rank returns [] when embedding_store is None."""
        ...


class TestRRFFuseThreeLists:
    def test_fuse_three_lists(self):
        """_rrf_fuse handles 3 input lists correctly."""
        from parrot.knowledge.pageindex.hybrid_search import HybridPageIndexSearch
        rankings = [
            ["a", "b", "c"],
            ["b", "c", "a"],
            ["c", "a", "b"],
        ]
        result = HybridPageIndexSearch._rrf_fuse(rankings)
        assert len(result) == 3
        # All three items should appear


class TestDirtyFlag:
    def test_dirty_rebuilds_matrix(self, small_tree):
        """mark_dirty triggers matrix rebuild on next _vec_rank call."""
        ...


class TestByteIdenticalBaseline:
    @pytest.mark.asyncio
    async def test_vec_disabled_matches_baseline(self, small_tree):
        """With use_vec=False, output identical to pre-embedding behavior."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/pageindex-embedding-router.spec.md` for full context
2. **Check dependencies** — verify TASK-1546 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — read `hybrid_search.py` to confirm current signatures
4. **Update status** in `sdd/tasks/index/pageindex-embedding-router.json` → `"in-progress"`
5. **Implement** following the scope and contract above
6. **Verify** all acceptance criteria are met — especially AC1 (byte-identical baseline)
7. **Move this file** to `sdd/tasks/completed/TASK-1547-dense-rrf-fusion.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-06-15
**Notes**: Added _vec_rank(), embedding_store/embed_fn/use_vec_rank/use_embedding_walk
params to HybridPageIndexSearch.__init__. Updated mark_dirty() to invalidate embedding
matrix. Updated search() with use_vec parameter and 3-way RRF fusion. When use_vec=False,
code path is byte-identical to baseline. All 14 unit tests pass.

**Deviations from spec**: none.
