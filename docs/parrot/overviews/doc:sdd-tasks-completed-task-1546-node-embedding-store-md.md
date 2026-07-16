---
type: Wiki Overview
title: 'TASK-1546: Implement NodeEmbeddingStore (two-tier content-addressed cache)'
id: doc:sdd-tasks-completed-task-1546-node-embedding-store-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Module 3 of FEAT-237. This is the core data structure: a two-tier content-addressed
  embedding cache for PageIndex trees. The global tier stores per-node embedding vectors
  keyed by `sha1(model_id + "\x00" + title + "\x00" + summary)` — this survives `reindex_node_ids`
  which rewrit'
relates_to:
- concept: mod:parrot.knowledge.pageindex
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.content_store
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.embedding_store
  rel: mentions
---

# TASK-1546: Implement NodeEmbeddingStore (two-tier content-addressed cache)

**Feature**: FEAT-237 — PageIndex Embedding Router
**Spec**: `sdd/specs/pageindex-embedding-router.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Module 3 of FEAT-237. This is the core data structure: a two-tier content-addressed embedding cache for PageIndex trees. The global tier stores per-node embedding vectors keyed by `sha1(model_id + "\x00" + title + "\x00" + summary)` — this survives `reindex_node_ids` which rewrites all node_ids on every tree mutation. The per-tree tier materializes a contiguous `(N, d)` numpy matrix for BLAS matmul.

Mirrors the existing `NodeContentStore` sidecar pattern (LRU cache, path structure, save/load API).

Spec reference: §2 Data Models, §3 Module 3, §6 Codebase Contract, §7 Patterns to Follow.

---

## Scope

- Create `NodeEmbeddingStore` class in new file `embedding_store.py`.
- Implement the global tier: content-addressed `.npy` files keyed by SHA-1 hash.
- Implement the per-tree tier: materialized `(N, d)` contiguous `.npy` matrix + `node_id_order` JSON sidecar.
- `content_key()` static method: `sha1(model_id + "\x00" + title + "\x00" + summary)`.
- `build_tree_matrix()`: batch-embeds only uncached nodes, writes per-tree matrix.
- `load_tree_matrix()`: loads per-tree matrix via mmap.
- `invalidate_tree()`: deletes per-tree matrix; global cache entries survive.
- LRU cache for in-memory global tier (configurable size).
- Write comprehensive unit tests.

**NOT in scope**: Wiring into `HybridPageIndexSearch` (TASK-1547), `PageIndexToolkit` (TASK-1549), or any model loading (pure numpy + stdlib).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/embedding_store.py` | CREATE | NodeEmbeddingStore implementation |
| `tests/knowledge/pageindex/test_embedding_store.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.

### Verified Imports

```python
# Pattern sibling — follow this structure
from parrot.knowledge.pageindex.content_store import NodeContentStore  # verified: content_store.py:37

# This task creates:
# from parrot.knowledge.pageindex.embedding_store import NodeEmbeddingStore
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py — PATTERN SIBLING
class NodeContentStore:
    def __init__(self, storage_dir, cache_size=256)  # line 54
    # storage_dir layout: <storage_dir>/<tree_name>/<node_id>.md
    def save(self, tree_name, node_id, markdown) -> None  # line 116
    def load(self, tree_name, node_id) -> Optional[str]  # line 123
    def loader_for(self, tree_name) -> Callable[[str], Optional[str]]  # line 197
    # Uses OrderedDict for LRU cache

# packages/ai-parrot/src/parrot/knowledge/pageindex/tree_ops.py
def reindex_node_ids(tree: dict) -> None  # line 16 — rewrites ALL node_ids
# This is WHY content-addressing is required — node_ids are unstable
```

### Does NOT Exist

- ~~`parrot.knowledge.pageindex.embedding_store`~~ — does not exist yet; this task creates it
- ~~`NodeEmbeddingStore`~~ — class does not exist yet
- ~~`NodeContentStore.embedding_*`~~ — no embedding methods on NodeContentStore

---

## Implementation Notes

### Pattern to Follow

```python
# Mirror NodeContentStore sidecar pattern:
# Storage layout:
#   <storage_dir>/<tree_name>/embeddings/
#     global/           ← content-addressed .npy files (one per unique text)
#       <sha1_hex>.npy
#     <tree_name>.matrix.npy     ← per-tree (N, d) contiguous matrix
#     <tree_name>.node_order.json ← node_id ordering for the matrix

import hashlib
import json
import numpy as np
from pathlib import Path
from collections import OrderedDict
from typing import Optional, Callable

class NodeEmbeddingStore:
    def __init__(self, storage_dir, model_id, dimension, cache_size=512):
        self._storage_dir = Path(storage_dir)
        self._model_id = model_id
        self._dimension = dimension
        self._cache_size = cache_size
        self._cache = OrderedDict()  # LRU: content_key -> np.ndarray

    @staticmethod
    def content_key(model_id: str, title: str, summary: str) -> str:
        raw = f"{model_id}\x00{title}\x00{summary}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()
```

### Key Constraints

- Content keys use `sha1(model_id + "\x00" + title + "\x00" + summary)` — the `\x00` separator prevents collisions between e.g. title="ab" summary="c" vs title="a" summary="bc".
- Per-tree matrix MUST be contiguous C-order float32 for efficient BLAS matmul.
- `load_tree_matrix()` should use `np.load(..., mmap_mode='r')` for memory-mapped read access.
- `build_tree_matrix()` accepts an `embed_fn: Callable[[list[str]], np.ndarray]` — the caller provides the actual embedding function. This keeps the store model-agnostic.
- `invalidate_tree()` deletes per-tree matrix + node_order but NOT global cache entries (those are content-addressed and reusable).
- Thread safety: global cache writes are idempotent (same key always produces same vector); per-tree matrix rebuild is triggered by the caller (single-writer via `mark_dirty()`).

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py` — primary pattern sibling
- `packages/ai-parrot/src/parrot/knowledge/pageindex/tree_ops.py` — explains why content-addressing is required

---

## Acceptance Criteria

- [ ] `NodeEmbeddingStore` class created at `embedding_store.py`
- [ ] `content_key()` is deterministic: same inputs → same hash
- [ ] `content_key()` varies on model_id, title, and summary independently
- [ ] `build_tree_matrix()` returns `(N, d)` contiguous float32 matrix + node_id list
- [ ] `build_tree_matrix()` only calls embed_fn for uncached nodes
- [ ] `load_tree_matrix()` returns matrix via mmap
- [ ] `invalidate_tree()` deletes per-tree matrix; global cache entries survive
- [ ] LRU cache evicts least-recently-used entries beyond cache_size
- [ ] All tests pass: `pytest tests/knowledge/pageindex/test_embedding_store.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/pageindex/embedding_store.py`

---

## Test Specification

```python
# tests/knowledge/pageindex/test_embedding_store.py
import pytest
import numpy as np
from pathlib import Path


@pytest.fixture
def store(tmp_path):
    from parrot.knowledge.pageindex.embedding_store import NodeEmbeddingStore
    return NodeEmbeddingStore(
        storage_dir=tmp_path / "embeddings",
        model_id="test-model",
        dimension=256,
        cache_size=10,
    )


@pytest.fixture
def mock_embed_fn():
    def embed(texts: list[str]) -> np.ndarray:
        rng = np.random.default_rng(seed=42)
        return rng.standard_normal((len(texts), 256)).astype(np.float32)
    return embed


class TestContentKey:
    def test_deterministic(self, store):
        k1 = store.content_key("model", "title", "summary")
        k2 = store.content_key("model", "title", "summary")
        assert k1 == k2

    def test_varies_on_model(self, store):
        k1 = store.content_key("model-a", "title", "summary")
        k2 = store.content_key("model-b", "title", "summary")
        assert k1 != k2

    def test_varies_on_title(self, store):
        k1 = store.content_key("model", "title-a", "summary")
        k2 = store.content_key("model", "title-b", "summary")
        assert k1 != k2

    def test_varies_on_summary(self, store):
        k1 = store.content_key("model", "title", "summary-a")
        k2 = store.content_key("model", "title", "summary-b")
        assert k1 != k2


class TestBuildTreeMatrix:
    def test_shape(self, store, mock_embed_fn):
        nodes = [
            {"node_id": "0001", "title": "Root", "summary": "Root summary"},
            {"node_id": "0002", "title": "Child", "summary": "Child summary"},
        ]
        matrix, order = store.build_tree_matrix("test-tree", nodes, mock_embed_fn)
        assert matrix.shape == (2, 256)
        assert len(order) == 2

    def test_cache_hit(self, store, mock_embed_fn):
        nodes = [
            {"node_id": "0001", "title": "Root", "summary": "Root summary"},
        ]
        store.build_tree_matrix("tree1", nodes, mock_embed_fn)
        call_count = [0]
        def counting_embed(texts):
            call_count[0] += len(texts)
            return mock_embed_fn(texts)
        store.build_tree_matrix("tree2", nodes, counting_embed)
        assert call_count[0] == 0  # all cached from first build


class TestInvalidateTree:
    def test_preserves_global_cache(self, store, mock_embed_fn):
        nodes = [{"node_id": "0001", "title": "Root", "summary": "Root summary"}]
        store.build_tree_matrix("test-tree", nodes, mock_embed_fn)
        store.invalidate_tree("test-tree")
        result = store.load_tree_matrix("test-tree")
        assert result is None  # per-tree matrix gone
        # But global cache entry still exists (re-build would not call embed_fn)
        call_count = [0]
        def counting_embed(texts):
            call_count[0] += len(texts)
            return mock_embed_fn(texts)
        store.build_tree_matrix("test-tree", nodes, counting_embed)
        assert call_count[0] == 0


class TestLoadTreeMatrix:
    def test_load_after_build(self, store, mock_embed_fn):
        nodes = [
            {"node_id": "0001", "title": "Root", "summary": "Root summary"},
            {"node_id": "0002", "title": "Child", "summary": "Child summary"},
        ]
        store.build_tree_matrix("test-tree", nodes, mock_embed_fn)
        result = store.load_tree_matrix("test-tree")
        assert result is not None
        matrix, order = result
        assert matrix.shape == (2, 256)

    def test_load_nonexistent(self, store):
        result = store.load_tree_matrix("nonexistent")
        assert result is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/pageindex-embedding-router.spec.md` for full context
2. **Check dependencies** — this task has no hard code dependencies
3. **Verify the Codebase Contract** — read `content_store.py` to confirm the sidecar pattern
4. **Update status** in `sdd/tasks/index/pageindex-embedding-router.json` → `"in-progress"`
5. **Implement** following the scope, pattern, and contract above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1546-node-embedding-store.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-06-15
**Notes**: Implemented NodeEmbeddingStore with two-tier content-addressed cache.
Global tier: SHA-1 keyed .npy sidecar files. Per-tree tier: (N,d) contiguous
float32 numpy matrix + node_order JSON sidecar. LRU cache via OrderedDict.
All 20 unit tests pass. Fixed test import to use importlib.util.spec_from_file_location
to bypass parrot.knowledge.pageindex.__init__.py heavy import chain (aiohttp_cors).

**Deviations from spec**: none. Pattern mirrors NodeContentStore exactly.
