---
type: Wiki Overview
title: 'TASK-1549: Wire NodeEmbeddingStore into PageIndexToolkit'
id: doc:sdd-tasks-completed-task-1549-toolkit-wiring-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Module 6 of FEAT-237. The `PageIndexToolkit` orchestrates tree lifecycle
  (create, search, persist, delete). This task wires the new `NodeEmbeddingStore`
  into the toolkit so that:'
relates_to:
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.embeddings.registry
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.content_store
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.embedding_store
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.hybrid_search
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.toolkit
  rel: mentions
---

# TASK-1549: Wire NodeEmbeddingStore into PageIndexToolkit

**Feature**: FEAT-237 — PageIndex Embedding Router
**Spec**: `sdd/specs/pageindex-embedding-router.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1546, TASK-1547
**Assigned-to**: unassigned

---

## Context

Module 6 of FEAT-237. The `PageIndexToolkit` orchestrates tree lifecycle (create, search, persist, delete). This task wires the new `NodeEmbeddingStore` into the toolkit so that:
1. The store is constructed once in `__init__` with configurable model/dimension.
2. `_search_for()` passes the store to `HybridPageIndexSearch`.
3. Tree mutations propagate the dirty flag to the embedding store.
4. Embedding model config params are exposed at toolkit level.

Spec reference: §3 Module 6, §6 Integration Points.

---

## Scope

- Add `embedding_model`, `embedding_dimension`, `embedding_backend`, `use_vec_rank`, `use_embedding_walk` params to `PageIndexToolkit.__init__`.
- Construct `NodeEmbeddingStore` in `__init__` (conditional: only if `use_vec_rank` or `use_embedding_walk`).
- Pass `NodeEmbeddingStore` + flags to `HybridPageIndexSearch` in `_search_for()`.
- In `_persist()` and other mutation points, propagate dirty flag to `NodeEmbeddingStore.invalidate_tree()`.
- Provide `_embed_fn` closure that uses `EmbeddingRegistry.get_or_create_sync()` to load the model and `encode()` for batch embedding.
- Write integration tests.

**NOT in scope**: The embedding store implementation (TASK-1546), dense ranking logic (TASK-1547), beam walk (TASK-1548), corpus (TASK-1550), or benchmark (TASK-1551).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | Wire NodeEmbeddingStore into init, _search_for, _persist |
| `tests/knowledge/pageindex/test_toolkit_embedding_wiring.py` | CREATE | Integration tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.

### Verified Imports

```python
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit  # verified: __init__.py
from parrot.knowledge.pageindex.hybrid_search import HybridPageIndexSearch  # verified
from parrot.knowledge.pageindex.content_store import NodeContentStore  # verified
from parrot.knowledge.pageindex.embedding_store import NodeEmbeddingStore  # from TASK-1546
from parrot.embeddings.registry import EmbeddingRegistry  # verified: registry.py:51
from parrot.conf import EMBEDDING_DEFAULT_MODEL, EMBEDDING_DEVICE  # verified: conf.py
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
class PageIndexToolkit(AbstractToolkit):
    def __init__(self, adapter, storage_dir, reranker=None,
                 lightweight_model=None, model=None,
                 default_bm25_k=20, folder_concurrency=4,
                 content_cache_size=256, **kwargs)  # line 76
    def _search_for(self, tree_name) -> HybridPageIndexSearch  # line 126
    def _persist(self, tree_name) -> None  # line 141 — calls engine.mark_dirty()

# packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py (after TASK-1547)
class HybridPageIndexSearch:
    def __init__(self, tree, adapter, reranker=None, model=None,
                 default_bm25_k=20, content_loader=None,
                 embedding_store=None,          # added by TASK-1547
                 use_vec_rank=False,             # added by TASK-1547
                 use_embedding_walk=False)       # added by TASK-1547

# packages/ai-parrot/src/parrot/embeddings/registry.py
class EmbeddingRegistry:
    @classmethod
    def instance(cls, max_models=None) -> "EmbeddingRegistry"  # line 100
    async def get_or_create(self, model_name, model_type="huggingface", **kwargs)  # line 218
    def get_or_create_sync(self, model_name, model_type="huggingface", **kwargs)  # line 345

# packages/ai-parrot/src/parrot/embeddings/base.py
class EmbeddingModel(ABC):
    async def encode(self, texts: List[str], **kwargs) -> np.ndarray  # line 226
```

### Does NOT Exist

- ~~`PageIndexToolkit.__init__(embedding_model=...)`~~ — parameter does not exist yet
- ~~`PageIndexToolkit._embedding_store`~~ — attribute does not exist yet
- ~~`PageIndexToolkit._embed_fn`~~ — attribute does not exist yet

---

## Implementation Notes

### Pattern to Follow

```python
# In PageIndexToolkit.__init__, add embedding config:
def __init__(self, adapter, storage_dir, ...,
             embedding_model=None,       # NEW
             embedding_dimension=256,    # NEW — default MRL dim
             embedding_backend=None,     # NEW — "torch"|"onnx"|"openvino"
             use_vec_rank=False,         # NEW
             use_embedding_walk=False,   # NEW
             **kwargs):
    ...
    # Construct embedding store if embedding features enabled
    self._use_vec_rank = use_vec_rank
    self._use_embedding_walk = use_embedding_walk
    self._embedding_store = None
    if use_vec_rank or use_embedding_walk:
        emb_model = embedding_model or EMBEDDING_DEFAULT_MODEL
        self._embedding_store = NodeEmbeddingStore(
            storage_dir=self._storage_dir,
            model_id=emb_model,
            dimension=embedding_dimension,
        )
        # Create embed_fn closure using the registry
        registry = EmbeddingRegistry.instance()
        self._embedding_model_name = emb_model
        self._embedding_backend = embedding_backend

# In _search_for(), pass the store:
def _search_for(self, tree_name):
    ...
    engine = HybridPageIndexSearch(
        tree=..., adapter=..., ...,
        embedding_store=self._embedding_store,
        use_vec_rank=self._use_vec_rank,
        use_embedding_walk=self._use_embedding_walk,
    )
    return engine
```

### Key Constraints

- `NodeEmbeddingStore` is constructed ONCE in `__init__`, shared across all tree searches.
- The `_embed_fn` passed to `build_tree_matrix` must use `EmbeddingRegistry.get_or_create_sync()` to avoid async in numpy operations.
- `_persist()` already calls `engine.mark_dirty()` — the dirty flag propagation to `NodeEmbeddingStore.invalidate_tree()` should happen inside `HybridPageIndexSearch.mark_dirty()` (already wired by TASK-1547). Verify this is working.
- Do NOT store embedding vectors inline in the tree JSON — the `_strip_keys_in_place` convention at toolkit.py:897 exists to keep the tree JSON lean.
- Backward compatible: if `use_vec_rank=False` and `use_embedding_walk=False` (the defaults), no embedding store is created and behavior is identical to pre-FEAT-237.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` — primary edit target
- `packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py` — how NodeContentStore is wired (sibling pattern)
- `packages/ai-parrot/src/parrot/conf.py` — `EMBEDDING_DEFAULT_MODEL`, `EMBEDDING_DEVICE`

---

## Acceptance Criteria

- [ ] `PageIndexToolkit` accepts `embedding_model`, `embedding_dimension`, `embedding_backend`, `use_vec_rank`, `use_embedding_walk`
- [ ] `NodeEmbeddingStore` constructed in `__init__` when embedding features enabled
- [ ] `_search_for()` passes store + flags to `HybridPageIndexSearch`
- [ ] Tree mutations propagate dirty flag to embedding store
- [ ] Default behavior (no embedding params) is unchanged
- [ ] `_embed_fn` closure correctly uses `EmbeddingRegistry` for model loading
- [ ] All tests pass: `pytest tests/knowledge/pageindex/test_toolkit_embedding_wiring.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py`

---

## Test Specification

```python
# tests/knowledge/pageindex/test_toolkit_embedding_wiring.py
import pytest
from unittest.mock import MagicMock, patch


class TestToolkitEmbeddingWiring:
    def test_no_embedding_by_default(self):
        """Without embedding params, no store is created."""
        # PageIndexToolkit with defaults
        ...

    def test_embedding_store_created_when_enabled(self):
        """With use_vec_rank=True, embedding store is constructed."""
        ...

    def test_search_for_passes_store(self):
        """_search_for passes embedding_store to HybridPageIndexSearch."""
        ...

    def test_dirty_propagation(self):
        """_persist triggers embedding store invalidation via mark_dirty."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/pageindex-embedding-router.spec.md` for full context
2. **Check dependencies** — verify TASK-1546 and TASK-1547 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — read `toolkit.py` to confirm current `__init__` and `_search_for` signatures
4. **Update status** in `sdd/tasks/index/pageindex-embedding-router.json` → `"in-progress"`
5. **Implement** following the scope and contract above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1549-toolkit-wiring.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-06-15
**Notes**: Added embedding_model/dimension/backend/use_vec_rank/use_embedding_walk to
PageIndexToolkit.__init__. NodeEmbeddingStore constructed when either feature enabled.
Lazy-loading _embed_fn closure uses EmbeddingRegistry.get_or_create_sync() + raw model.
_search_for passes store/embed_fn/flags to HybridPageIndexSearch. All 7 tests pass.

**Deviations from spec**: none.
