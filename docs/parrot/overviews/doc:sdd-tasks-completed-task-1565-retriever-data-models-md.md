---
type: Wiki Overview
title: 'TASK-1565: Core Data Models and Retriever Skeleton'
id: doc:sdd-tasks-completed-task-1565-retriever-data-models-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the foundation task for the Graph-Expanded Retrieval Pipeline (FEAT-217).
relates_to:
- concept: mod:parrot.knowledge.graphindex.communities
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.embed
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.retriever
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.schema
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.signals
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.hybrid_search
  rel: mentions
---

# TASK-1565: Core Data Models and Retriever Skeleton

**Feature**: FEAT-217 — Graph-Expanded Retrieval Pipeline
**Spec**: `sdd/specs/FEAT-217-graph-expanded-retrieval.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundation task for the Graph-Expanded Retrieval Pipeline (FEAT-217).
It creates the new `retriever.py` module with all Pydantic data models and the
`GraphExpandedRetriever` class skeleton with its `__init__` method. All subsequent
tasks build on this.

Implements spec Section 2 (Data Models) and Section 3 (Module 1: Core Retriever Class).

---

## Scope

- Create `retriever.py` with Pydantic models: `ExpansionConfig`, `BudgetConfig`, `ScoredNode`, `GraphRetrievalResult`
- Create `GraphExpandedRetriever` class with `__init__` that accepts and stores component references
- Validate at init: at least one of `hybrid_search` or `embedder` must be provided (raise `ValueError` otherwise)
- Add a stub `async def search()` that raises `NotImplementedError` (wired in TASK-1568)
- Add logger via `logging.getLogger(__name__)`

**NOT in scope**: Phase 1–4 implementation (TASK-1566–1568), toolkit integration (TASK-1569)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/retriever.py` | CREATE | Data models + GraphExpandedRetriever class skeleton |
| `packages/ai-parrot/tests/knowledge/graphindex/test_retriever.py` | CREATE | Tests for models and init validation |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports

```python
# verified: packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py
from parrot.knowledge.graphindex.schema import (
    UniversalNode,   # line 70
)

# verified: packages/ai-parrot/src/parrot/knowledge/graphindex/signals.py
from parrot.knowledge.graphindex.signals import (
    SignalRelevanceConfig,  # line 89
)

# verified: packages/ai-parrot/src/parrot/knowledge/graphindex/communities.py
from parrot.knowledge.graphindex.communities import (
    CommunitiesResult,      # line 69
)

# verified: packages/ai-parrot/src/parrot/knowledge/graphindex/embed.py
from parrot.knowledge.graphindex.embed import GraphIndexEmbedder  # line 25

# verified: packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py
from parrot.knowledge.pageindex.hybrid_search import HybridPageIndexSearch  # line 52
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/embed.py:25
class GraphIndexEmbedder:
    async def search_similar(self, query_text: str, top_k: int = 10) -> list[tuple[str, float]]:  # line 122
        """Returns list of (node_id, distance) sorted by ascending L2 distance."""

# packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py:52
class HybridPageIndexSearch:
    async def search(
        self, query: str, top_k: int = 10,
        use_bm25: bool = True, use_llm_walk: bool = True,
        use_vec: bool = False, use_embedding_walk: Optional[bool] = None,
        rerank: bool = False,
    ) -> list[dict[str, Any]]:  # line 288

# packages/ai-parrot/src/parrot/knowledge/graphindex/communities.py:69
class CommunitiesResult(BaseModel):
    modularity: float
    resolution: float
    seed: int
    weighted: bool
    communities: list[Community]
    node_to_community: dict[str, str]
```

### Does NOT Exist

- ~~`parrot.knowledge.graphindex.retriever`~~ — this task creates it
- ~~`GraphExpandedRetriever`~~ — this task creates it
- ~~`GraphIndexEmbedder.search()`~~ — method is `search_similar()`, not `search()`
- ~~`GraphIndexEmbedder.search_similar(query_embedding: np.ndarray, ...)`~~ — actual signature takes `query_text: str`, NOT `np.ndarray`

---

## Implementation Notes

### Pattern to Follow

Follow the same Pydantic model + class-with-components pattern used in the codebase:

```python
import logging
from typing import Optional
from pydantic import BaseModel, Field

class ExpansionConfig(BaseModel):
    """Configuration for graph expansion phase."""
    max_hops: int = Field(default=2, ge=1, le=4)
    decay_base: float = Field(default=0.7, gt=0.0, le=1.0)
    min_signal_threshold: float = Field(default=0.1, ge=0.0)
    max_expanded_nodes: int = Field(default=50, ge=1)
    include_community_centroids: bool = False

class GraphExpandedRetriever:
    def __init__(self, graph, nodes, embedder=None, hybrid_search=None, ...):
        if embedder is None and hybrid_search is None:
            raise ValueError("At least one of embedder or hybrid_search must be provided")
        self.logger = logging.getLogger(__name__)
        ...
```

### Key Constraints
- All models use Pydantic `BaseModel` with `Field` for validation
- `ScoredNode` must carry decomposed scores: `search_score`, `signal_score`, `decay_factor`, `combined_score`
- `GraphRetrievalResult` must include metadata: `total_candidates`, `nodes_expanded`, `communities_touched`, `budget_used`, `budget_limit`, `truncated`
- Constructor stores references; does NOT import or construct the components

---

## Acceptance Criteria

- [ ] `retriever.py` created at `packages/ai-parrot/src/parrot/knowledge/graphindex/retriever.py`
- [ ] All 4 Pydantic models defined: `ExpansionConfig`, `BudgetConfig`, `ScoredNode`, `GraphRetrievalResult`
- [ ] `GraphExpandedRetriever.__init__` stores all component references
- [ ] `ValueError` raised when both `embedder` and `hybrid_search` are None
- [ ] Stub `search()` method present (raises `NotImplementedError`)
- [ ] Import works: `from parrot.knowledge.graphindex.retriever import GraphExpandedRetriever, ExpansionConfig, BudgetConfig, ScoredNode, GraphRetrievalResult`
- [ ] Tests pass: `pytest packages/ai-parrot/tests/knowledge/graphindex/test_retriever.py -v -k "model or init"`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/graphindex/retriever.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/graphindex/test_retriever.py
import pytest
from pydantic import ValidationError


class TestExpansionConfig:
    def test_defaults(self):
        """Default config has max_hops=2, decay_base=0.7."""
        from parrot.knowledge.graphindex.retriever import ExpansionConfig
        cfg = ExpansionConfig()
        assert cfg.max_hops == 2
        assert cfg.decay_base == 0.7

    def test_validation_max_hops(self):
        """max_hops must be 1..4."""
        from parrot.knowledge.graphindex.retriever import ExpansionConfig
        with pytest.raises(ValidationError):
            ExpansionConfig(max_hops=0)
        with pytest.raises(ValidationError):
            ExpansionConfig(max_hops=5)


class TestBudgetConfig:
    def test_defaults(self):
        from parrot.knowledge.graphindex.retriever import BudgetConfig
        cfg = BudgetConfig()
        assert cfg.max_tokens == 8000


class TestScoredNode:
    def test_seed_node(self):
        from parrot.knowledge.graphindex.retriever import ScoredNode
        node = ScoredNode(node_id="n1", title="Test", kind="document", is_seed=True, search_score=0.9)
        assert node.is_seed is True
        assert node.hop_distance == 0


class TestGraphExpandedRetriever:
    def test_init_requires_at_least_one_source(self):
        """ValueError when neither embedder nor hybrid_search provided."""
        from parrot.knowledge.graphindex.retriever import GraphExpandedRetriever
        import rustworkx
        graph = rustworkx.PyDiGraph()
        with pytest.raises(ValueError, match="at least one"):
            GraphExpandedRetriever(graph=graph, nodes=[])
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-217-graph-expanded-retrieval.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — confirm imports still exist
4. **Update status** in `sdd/tasks/index/FEAT-217-graph-expanded-retrieval.json` → `"in-progress"`
5. **Implement** following the scope and codebase contract above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1565-retriever-data-models.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: 
